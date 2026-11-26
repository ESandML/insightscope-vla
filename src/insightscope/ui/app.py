"""Gradio UI wiring.

Every decision of substance lives elsewhere: ``ui.state`` decides what the audio
controls show, ``ui.service`` runs an audit through the shared pipeline, and
``inputs.plan_for`` builds the routing plan. This file only moves values between
Gradio components and those functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import gradio as gr
import yaml

from insightscope.actions.db import history
from insightscope.domain.checklist import ChecklistSpec, load_checklist
from insightscope.inputs import plan_for
from insightscope.ui.service import (
    HISTORY_COLUMNS,
    UiRequest,
    UiRunResult,
    generate_spec_text,
    run_ui_audit,
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


def _parse_spec_text(text: str) -> ChecklistSpec:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("audit spec must be a YAML mapping")
    return ChecklistSpec.model_validate(raw)


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


def on_spec_upload(file: Any) -> Any:
    path = _as_path(file)
    if path is None:
        return gr.update()
    return path.read_text(encoding="utf-8")


def on_generate(
    process_text: str,
    client: str,
    cassette: Any,
) -> tuple[Any, str]:
    try:
        text = generate_spec_text(
            process_text,
            client=_client_key(client),
            cassette_path=_as_path(cassette),
        )
    except Exception as exc:
        return gr.update(), f"**error:** {exc}"
    return text, "Spec generated. Review or edit it, then **Run Audit**."


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
    client: str,
    cassette: Any,
    flag_omissions: bool,
    progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio's injection pattern
) -> tuple[Any, ...]:
    clip = _as_path(video)
    if clip is None:
        return _error_outputs("Upload a video first.", spec_text)

    audio_path = _as_path(audio_file)
    upload = _as_path(spec_upload)

    try:
        if upload is not None:
            spec = load_checklist(upload)
            reference, generated = "spec", False
        elif spec_text.strip():
            spec = _parse_spec_text(spec_text)
            reference, generated = "spec", False
        elif process_text.strip():
            generated_text = generate_spec_text(
                process_text,
                client=_client_key(client),
                cassette_path=_as_path(cassette),
            )
            spec = _parse_spec_text(generated_text)
            spec_text = generated_text
            reference, generated = "process", True
        else:
            spec, reference, generated = None, "none", False

        if reference == "none" and not listen_value and audio_path is None:
            return _error_outputs(
                "Choose a reference (process/spec) or enable a speech source.",
                spec_text,
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
            ),
            on_stage=_stage_callback(progress),
        )
    except Exception as exc:
        return _error_outputs(f"{type(exc).__name__}: {exc}", spec_text)

    if result.error is not None:
        return _error_outputs(result.error, spec_text)
    return _success_outputs(result, spec_text)


def _stage_callback(progress: gr.Progress) -> Any:
    seen = {"count": 0}

    def on_stage(stage: str) -> None:
        seen["count"] += 1
        progress(min(0.95, seen["count"] / 14), desc=stage.replace("_", " "))

    return on_stage


def _error_outputs(message: str, spec_text: str = "") -> tuple[Any, ...]:
    return (
        f"**error**\n\n{message}",
        [],
        [],
        "",
        spec_text,
        "",
        _history_value(()),
    )


def _success_outputs(result: UiRunResult, fallback_spec: str) -> tuple[Any, ...]:
    status = f"**{result.status}** · run `{result.run_id}` · {len(result.keyframes)} keyframes"
    return (
        status,
        [list(item) for item in result.keyframes],
        list(result.flagged),
        result.assertions_json,
        result.spec_yaml or fallback_spec,
        result.report_markdown,
        _history_value(result.history),
    )


def build_ui() -> gr.Blocks:
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
                process_text = gr.Textbox(
                    label="Process description",
                    lines=3,
                    placeholder="fill the kettle, boil it, pour water into the mug",
                )
                generate = gr.Button("Generate Spec")
                spec_upload = gr.File(
                    label="Audit spec (.yaml)",
                    file_types=[".yaml", ".yml"],
                    type="filepath",
                )
                with gr.Accordion("Run settings", open=False):
                    client = gr.Radio(
                        CLIENT_CHOICES,
                        value="fake",
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
                with gr.Tab("Assertions & Spec"):
                    assertions = gr.Code(
                        label="Claims, observations, findings",
                        language="json",
                        lines=18,
                    )
                    spec_text = gr.Textbox(
                        label="Audit spec (editable YAML)",
                        lines=16,
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
        generate.click(on_generate, [process_text, client, cassette], [spec_text, status])
        spec_upload.change(on_spec_upload, [spec_upload], [spec_text])
        run.click(
            on_run,
            [
                video,
                listen,
                audio_file,
                process_text,
                spec_text,
                spec_upload,
                client,
                cassette,
                omissions,
            ],
            [status, keyframes, flagged, assertions, spec_text, report, history_df],
            show_progress="full",
        )
        demo.load(on_load_history, None, [history_df])

    return cast(gr.Blocks, demo)


def main() -> int:
    build_ui().launch(server_name="127.0.0.1", share=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
