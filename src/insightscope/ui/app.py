"""Gradio UI wiring.

Every decision of substance lives elsewhere: ``ui.state`` decides what the audio
controls show, ``ui.specs`` owns spec browsing and persistence, ``ui.service`` runs an
audit through the shared pipeline, and ``inputs.plan_for`` builds the routing plan. This
file only moves values between Gradio components and those functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import gradio as gr

from insightscope.actions.db import history
from insightscope.config import Settings
from insightscope.inputs import plan_for
from insightscope.ui.service import (
    HISTORY_COLUMNS,
    UiRequest,
    UiRunResult,
    generate_spec_text,
    run_ui_audit,
)
from insightscope.ui.specs import (
    default_spec_name,
    dropdown_update,
    initial_spec_text,
    read_spec_text,
    save_spec_text,
    spec_names,
)
from insightscope.ui.state import audio_state

CLIENT_CHOICES = ["fake", "ollama", "cassette replay"]


def _as_path(value: Any) -> Path | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return _as_path(value[0]) if value else None
    if isinstance(value, (str, Path)):
        return Path(value)
    name = getattr(value, "name", None)
    return Path(name) if name else None


def _client_key(choice: str) -> str:
    return "cassette" if choice == "cassette replay" else choice


def _root(specs_dir: Path | None) -> Path:
    return Path(specs_dir) if specs_dir is not None else Settings().specs_dir


def _history_value(rows: tuple[tuple[object, ...], ...]) -> list[list[object]]:
    return [list(row) for row in rows]


def on_sources(video: Any, audio: Any) -> tuple[Any, Any, str]:
    """React to a new video or external audio file."""
    state = audio_state(_as_path(video), _as_path(audio))
    return (
        gr.update(interactive=state.listen_available, value=state.listen_value),
        gr.update(visible=state.show_upload),
        state.status,
    )


def on_client_change(choice: str) -> Any:
    return gr.update(visible=_client_key(choice) == "cassette")


def on_spec_upload(file: Any, specs_dir: Path | None = None) -> tuple[Any, Any, str]:
    root = _root(specs_dir)
    path = _as_path(file)
    if path is None:
        return gr.update(), dropdown_update(root), ""

    try:
        text = path.read_text(encoding="utf-8")
        saved = save_spec_text(text, root)
    except Exception as exc:
        return gr.update(), dropdown_update(root), f"**error:** {exc}"

    return saved.text, dropdown_update(root, saved.path.name), f"Saved to `{saved.path}`."


def on_select_spec(name: str | None, specs_dir: Path | None = None) -> tuple[Any, str]:
    root = _root(specs_dir)
    if not name:
        return gr.update(), "Select a saved spec."
    try:
        return read_spec_text(name, root), f"Loaded `{name}`."
    except Exception as exc:
        return gr.update(), f"**error:** {exc}"


def on_save_spec(
    spec_text: str,
    selected_spec: str | None = None,
    specs_dir: Path | None = None,
) -> tuple[Any, Any, str]:
    root = _root(specs_dir)
    try:
        saved = save_spec_text(spec_text, root, selected_spec or None)
    except Exception as exc:
        return gr.update(), dropdown_update(root), f"**error:** {exc}"
    return saved.text, dropdown_update(root, saved.path.name), f"Saved to `{saved.path}`."


def on_generate(
    process_text: str,
    client: str,
    cassette: Any,
    specs_dir: Path | None = None,
) -> tuple[Any, Any, str]:
    root = _root(specs_dir)
    try:
        text = generate_spec_text(
            process_text,
            client=_client_key(client),
            cassette_path=_as_path(cassette),
        )
        saved = save_spec_text(text, root)
    except Exception as exc:
        return gr.update(), dropdown_update(root), f"**error:** {exc}"

    warning = ""
    if _client_key(client) == "fake":
        warning = (
            " The fake client returns a scripted coffee fixture, so this file is a "
            "placeholder — switch to ollama for a spec based on your description."
        )
    return (
        saved.text,
        dropdown_update(root, saved.path.name),
        f"Spec saved to `{saved.path}`.{warning}",
    )


def on_load_history() -> list[list[object]]:
    return _history_value(
        tuple(
            tuple(row.get(column) for column in HISTORY_COLUMNS)
            for row in history(Path("audits.db"), limit=20)
        )
    )


def on_run(
    video: Any,
    listen_value: bool,
    audio_file: Any,
    process_text: str,
    spec_text: str,
    spec_upload: Any,
    selected_spec: str | None,
    client: str,
    cassette: Any,
    flag_omissions: bool,
    specs_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    db_path: Path | None = None,
    progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio's injection pattern
) -> tuple[Any, ...]:
    root = _root(specs_dir)
    clip = _as_path(video)
    if clip is None:
        return _error_outputs("Upload a video first.", spec_text, root)

    audio_path = _as_path(audio_file)
    upload = _as_path(spec_upload)

    try:
        if upload is not None:
            saved_upload = save_spec_text(upload.read_text(encoding="utf-8"), root)
            spec, spec_text = saved_upload.spec, saved_upload.text
            reference, generated = "spec", False
        elif spec_text.strip():
            # Persist edits before running, so the file on disk is what ran.
            saved_edit = save_spec_text(spec_text, root, selected_spec or None)
            spec, spec_text = saved_edit.spec, saved_edit.text
            reference, generated = "spec", False
        elif process_text.strip():
            generated_text = generate_spec_text(
                process_text,
                client=_client_key(client),
                cassette_path=_as_path(cassette),
            )
            saved_process = save_spec_text(generated_text, root)
            spec, spec_text = saved_process.spec, saved_process.text
            reference, generated = "process", True
        else:
            spec, reference, generated = None, "none", False

        if reference == "none" and not listen_value and audio_path is None:
            return _error_outputs(
                "Choose a reference (process/spec) or enable a speech source.",
                spec_text,
                root,
            )

        plan = plan_for(
            listen=bool(listen_value),
            audio=audio_path is not None,
            process=reference == "process",
            spec=reference == "spec",
        )
        result = run_ui_audit(
            UiRequest(
                clip=clip,
                plan=plan,
                audio_path=audio_path,
                spec=spec,
                generated_spec=generated,
                flag_omissions=bool(flag_omissions),
                client=_client_key(client),
                cassette_path=_as_path(cassette),
                specs_dir=root,
                artifacts_dir=artifacts_dir or Path("artifacts"),
                db_path=db_path or Path("audits.db"),
            ),
            on_stage=_stage_callback(progress),
        )
    except Exception as exc:
        return _error_outputs(f"{type(exc).__name__}: {exc}", spec_text, root)

    if result.error is not None:
        return _error_outputs(result.error, spec_text, root)
    return _success_outputs(result, spec_text, root)


def _stage_callback(progress: gr.Progress) -> Any:
    seen = {"count": 0}

    def on_stage(stage: str) -> None:
        seen["count"] += 1
        progress(min(0.95, seen["count"] / 14), desc=stage.replace("_", " "))

    return on_stage


def _error_outputs(message: str, spec_text: str, specs_dir: Path) -> tuple[Any, ...]:
    return (
        f"**error**\n\n{message}",
        [],
        [],
        "",
        spec_text,
        "",
        _history_value(()),
        dropdown_update(specs_dir),
    )


def _success_outputs(result: UiRunResult, fallback_spec: str, specs_dir: Path) -> tuple[Any, ...]:
    status = f"**{result.status}** · run `{result.run_id}` · {len(result.keyframes)} keyframes"
    return (
        status,
        [list(item) for item in result.keyframes],
        list(result.flagged),
        result.assertions_json,
        result.spec_yaml or fallback_spec,
        result.report_markdown,
        _history_value(result.history),
        dropdown_update(specs_dir, result.spec_name or None),
    )


def build_ui() -> gr.Blocks:
    specs_dir = Settings().specs_dir
    choices = spec_names(specs_dir)
    selected = default_spec_name(specs_dir)
    initial_yaml = initial_spec_text(specs_dir)

    with gr.Blocks(title="InsightScope-VLA") as demo:
        gr.Markdown(
            "# InsightScope-VLA\n"
            "Audit what a camera saw against what was said or planned. "
            "All routing goes through the same pipeline as the CLI."
        )

        with gr.Row():
            with gr.Column(scale=4):
                video = gr.Video(label="Clip", sources=["upload"])
                source_status = gr.Markdown("Upload a video to begin.")
                listen = gr.Checkbox(
                    label="Listen to video audio",
                    value=False,
                    interactive=False,
                )
                audio_file = gr.File(
                    label="External audio (.wav / .mp3 / .m4a)",
                    file_types=[".wav", ".mp3", ".m4a"],
                    type="filepath",
                    visible=False,
                )
                spec_choice = gr.Dropdown(
                    label="Saved audit spec (specs/)",
                    choices=choices,
                    value=selected,
                )
                spec_text = gr.Textbox(
                    label="Audit spec (editable YAML)",
                    lines=14,
                    value=initial_yaml,
                )
                save_spec = gr.Button("Save Spec")
                spec_upload = gr.File(
                    label="Upload audit spec (.yaml)",
                    file_types=[".yaml", ".yml"],
                    type="filepath",
                )
                process_text = gr.Textbox(
                    label="Process description",
                    lines=3,
                    placeholder="fill the kettle, add a tea bag, pour water, add milk",
                )
                generate = gr.Button("Generate Spec")
                with gr.Accordion("Run settings", open=False):
                    client = gr.Radio(
                        CLIENT_CHOICES,
                        value="ollama",
                        label="Client",
                    )
                    cassette = gr.File(
                        label="Cassette (.json)",
                        file_types=[".json"],
                        type="filepath",
                        visible=False,
                    )
                    omissions = gr.Checkbox(
                        label="Flag omissions (noisy)",
                        value=False,
                    )
                run = gr.Button("Run Audit", variant="primary")
                status = gr.Markdown("")

            with gr.Column(scale=8), gr.Tabs():
                with gr.Tab("Keyframes"):
                    keyframes = gr.Gallery(
                        label="Selected frames",
                        columns=4,
                        height=420,
                    )
                with gr.Tab("Flagged"):
                    flagged = gr.Gallery(
                        label="Annotated findings",
                        columns=3,
                        height=420,
                    )
                with gr.Tab("Assertions"):
                    assertions = gr.Code(
                        label="Claims, observations, findings",
                        language="json",
                        lines=18,
                    )
                with gr.Tab("Report"):
                    report = gr.Markdown()
                with gr.Tab("History"):
                    history_df = gr.Dataframe(
                        headers=list(HISTORY_COLUMNS),
                        interactive=False,
                    )

        video.change(
            on_sources,
            [video, audio_file],
            [listen, audio_file, source_status],
        )
        audio_file.change(
            on_sources,
            [video, audio_file],
            [listen, audio_file, source_status],
        )
        client.change(on_client_change, [client], [cassette])
        spec_choice.change(on_select_spec, [spec_choice], [spec_text, status])
        spec_upload.change(
            on_spec_upload,
            [spec_upload],
            [spec_text, spec_choice, status],
        )
        generate.click(
            on_generate,
            [process_text, client, cassette],
            [spec_text, spec_choice, status],
        )
        save_spec.click(
            on_save_spec,
            [spec_text, spec_choice],
            [spec_text, spec_choice, status],
        )
        run.click(
            on_run,
            [
                video,
                listen,
                audio_file,
                process_text,
                spec_text,
                spec_upload,
                spec_choice,
                client,
                cassette,
                omissions,
            ],
            [
                status,
                keyframes,
                flagged,
                assertions,
                spec_text,
                report,
                history_df,
                spec_choice,
            ],
            show_progress="full",
        )
        demo.load(on_load_history, None, [history_df])

    return cast(gr.Blocks, demo)


def main() -> int:
    build_ui().launch(server_name="127.0.0.1", share=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
