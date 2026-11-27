"""Gradio UI wiring.

Every decision of substance lives elsewhere: ``ui.state`` decides what the audio
controls show, ``ui.specs`` owns validation and persistence, ``ui.service`` runs an audit
through the shared pipeline, and ``inputs.plan_for`` builds the routing plan. This file
only moves values between Gradio components and those functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import gradio as gr

from insightscope.actions.db import history
from insightscope.config import Settings
from insightscope.domain.checklist import ChecklistError
from insightscope.inputs import plan_for
from insightscope.ui.service import (
    HISTORY_COLUMNS,
    UiRequest,
    UiRunResult,
    generate_spec_text,
    run_ui_audit,
)
from insightscope.ui.specs import (
    NEW_SPEC,
    delete_enabled,
    delete_spec,
    dropdown_update,
    ensure_new_filename,
    fallback_choice,
    generate_enabled,
    initial_choice,
    initial_spec_text,
    read_spec_text,
    save_enabled,
    save_existing_spec,
    save_new_spec,
    save_uploaded_spec,
    spec_choices,
    spec_names,
    validate_spec_yaml,
    validation_message,
)
from insightscope.ui.state import audio_state

CLIENT_CHOICES = ["fake", "ollama", "cassette replay"]

EDITOR_OUTPUTS = 8


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


def _editor(
    *,
    text: str | None,
    choice_update: Any | None,
    filename_update: Any | None,
    baseline: str,
    generate_on: bool | None,
    save_on: bool | None,
    delete_on: bool | None,
    validation: str,
    status: str,
) -> tuple[Any, ...]:
    """The nine outputs every spec-editing handler returns."""
    return (
        gr.update(value=text) if isinstance(text, str) else gr.update(),
        choice_update if choice_update is not None else gr.update(),
        filename_update if filename_update is not None else gr.update(),
        baseline,
        gr.update(interactive=generate_on) if generate_on is not None else gr.update(),
        gr.update(interactive=save_on) if save_on is not None else gr.update(),
        gr.update(interactive=delete_on) if delete_on is not None else gr.update(),
        validation,
        status,
    )


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


def _load_choice(
    choice: str,
    root: Path,
    process_text: str,
    *,
    note: str | None = None,
) -> tuple[Any, ...]:
    """Load a spec (or a fresh editor) and refresh the dropdown from disk."""
    if choice == NEW_SPEC:
        return _editor(
            text="",
            choice_update=dropdown_update(root, NEW_SPEC),
            filename_update=gr.update(visible=True, value=""),
            baseline="",
            generate_on=False,
            save_on=False,
            delete_on=False,
            validation="",
            status=note or "New spec: enter a file name and a process description, or type YAML.",
        )

    try:
        text = read_spec_text(choice, root)
    except Exception as exc:
        return _editor(
            text=None,
            choice_update=dropdown_update(root, NEW_SPEC),
            filename_update=gr.update(visible=True, value=""),
            baseline="",
            generate_on=False,
            save_on=False,
            delete_on=False,
            validation="",
            status=f"**error:** {exc}",
        )

    return _editor(
        text=text,
        choice_update=dropdown_update(root, choice),
        filename_update=gr.update(visible=False, value=""),
        baseline=text,
        generate_on=generate_enabled(choice, "", process_text),
        save_on=False,
        delete_on=delete_enabled(choice),
        validation="",
        status=note or f"Loaded `{choice}`. Save enables when the YAML is valid and changed.",
    )


def on_choice(
    choice: str,
    process_text: str,
    specs_dir: Path | None = None,
) -> tuple[Any, ...]:
    """Dropdown changed: re-read the directory, then load or fall back cleanly."""
    root = _root(specs_dir)

    if choice != NEW_SPEC and choice not in spec_names(root):
        fallback = fallback_choice(root)
        return _load_choice(
            fallback,
            root,
            process_text,
            note=f"`{choice}` is no longer on disk; removed it from the list.",
        )

    return _load_choice(choice, root, process_text)


def on_new_filename(
    filename: str,
    choice: str,
    process_text: str,
    spec_text: str,
    baseline: str,
) -> tuple[Any, Any]:
    return (
        gr.update(interactive=generate_enabled(choice, filename, process_text)),
        gr.update(interactive=save_enabled(choice, spec_text, baseline, filename)),
    )


def on_process(process_text: str, choice: str, filename: str) -> Any:
    return gr.update(interactive=generate_enabled(choice, filename, process_text))


def on_spec_text(
    spec_text: str,
    choice: str,
    baseline: str,
    filename: str,
) -> tuple[str, Any]:
    return (
        validation_message(spec_text),
        gr.update(interactive=save_enabled(choice, spec_text, baseline, filename)),
    )


def on_generate(
    process_text: str,
    client: str,
    cassette: Any,
    choice: str,
    filename: str,
    baseline: str,
    specs_dir: Path | None = None,
) -> tuple[Any, ...]:
    root = _root(specs_dir)
    if not process_text.strip():
        return _editor(
            text=None,
            choice_update=None,
            filename_update=None,
            baseline=baseline,
            generate_on=False,
            save_on=None,
            delete_on=None,
            validation="",
            status="Enter a process description first.",
        )

    warning = ""
    if _client_key(client) == "fake":
        warning = (
            " The fake client returns a scripted coffee fixture, so this is a "
            "placeholder — switch to ollama for a spec based on your description."
        )

    try:
        if choice == NEW_SPEC:
            ensure_new_filename(filename, root)

        text = generate_spec_text(
            process_text,
            client=_client_key(client),
            cassette_path=_as_path(cassette),
        )
        valid, message = validate_spec_yaml(text)
        if not valid:
            raise ChecklistError(message)

        saved = save_new_spec(text, filename, root) if choice == NEW_SPEC else None
    except Exception as exc:
        return _editor(
            text=None,
            choice_update=None,
            filename_update=None,
            baseline=baseline,
            generate_on=None,
            save_on=None,
            delete_on=None,
            validation="",
            status=f"**error:** {exc}",
        )

    if saved is not None:
        return _editor(
            text=saved.text,
            choice_update=dropdown_update(root, saved.path.name),
            filename_update=gr.update(visible=False, value=""),
            baseline=saved.text,
            generate_on=False,
            save_on=False,
            delete_on=True,
            validation="",
            status=f"Spec saved to `{saved.path}`.{warning}",
        )

    return _editor(
        text=text,
        choice_update=None,
        filename_update=gr.update(visible=False),
        baseline=baseline,
        generate_on=generate_enabled(choice, filename, process_text),
        save_on=save_enabled(choice, text, baseline, filename),
        delete_on=True,
        validation=validation_message(text),
        status=(
            f"Regenerated from the description. Review and **Save Spec** to update "
            f"`{choice}`.{warning}"
        ),
    )


def on_save(
    spec_text: str,
    choice: str,
    baseline: str,
    filename: str,
    specs_dir: Path | None = None,
) -> tuple[Any, ...]:
    root = _root(specs_dir)
    try:
        if choice == NEW_SPEC:
            saved = save_new_spec(spec_text, filename, root)
        else:
            saved = save_existing_spec(spec_text, choice, root)
    except Exception as exc:
        return _editor(
            text=None,
            choice_update=None,
            filename_update=None,
            baseline=baseline,
            generate_on=None,
            save_on=None,
            delete_on=None,
            validation=validation_message(spec_text),
            status=f"**error:** {exc}",
        )

    return _editor(
        text=saved.text,
        choice_update=dropdown_update(root, saved.path.name),
        filename_update=gr.update(visible=False, value=""),
        baseline=saved.text,
        generate_on=False,
        save_on=False,
        delete_on=True,
        validation="",
        status=f"Saved to `{saved.path}`.",
    )


def on_spec_upload(
    file: Any,
    baseline: str,
    specs_dir: Path | None = None,
) -> tuple[Any, ...]:
    root = _root(specs_dir)
    path = _as_path(file)
    if path is None:
        return _editor(
            text=None,
            choice_update=None,
            filename_update=None,
            baseline=baseline,
            generate_on=None,
            save_on=None,
            delete_on=None,
            validation="",
            status="",
        )

    try:
        saved = save_uploaded_spec(path.read_text(encoding="utf-8"), path.name, root)
    except Exception as exc:
        return _editor(
            text=None,
            choice_update=None,
            filename_update=None,
            baseline=baseline,
            generate_on=None,
            save_on=None,
            delete_on=None,
            validation="",
            status=f"**error:** {exc}",
        )

    return _editor(
        text=saved.text,
        choice_update=dropdown_update(root, saved.path.name),
        filename_update=gr.update(visible=False, value=""),
        baseline=saved.text,
        generate_on=False,
        save_on=False,
        delete_on=True,
        validation="",
        status=f"Saved to `{saved.path}`.",
    )


def on_delete(
    choice: str,
    process_text: str,
    baseline: str,
    specs_dir: Path | None = None,
) -> tuple[Any, ...]:
    """Delete the selected spec and load whatever remains."""
    root = _root(specs_dir)
    try:
        delete_spec(choice, root)
    except Exception as exc:
        return _editor(
            text=None,
            choice_update=dropdown_update(root, choice),
            filename_update=None,
            baseline=baseline,
            generate_on=None,
            save_on=None,
            delete_on=None,
            validation="",
            status=f"**error:** {exc}",
        )

    fallback = fallback_choice(root)
    note = f"Deleted `{choice}`."
    if fallback == NEW_SPEC:
        note += " No specs left; create a new one."
    else:
        note += f" Selected `{fallback}`."
    return _load_choice(fallback, root, process_text, note=note)


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
    selected_spec: str,
    new_filename: str,
    client: str,
    cassette: Any,
    flag_omissions: bool,
    baseline: str,
    specs_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    db_path: Path | None = None,
    progress: gr.Progress = gr.Progress(),  # noqa: B008 - Gradio's injection pattern
) -> tuple[Any, ...]:
    root = _root(specs_dir)
    clip = _as_path(video)
    if clip is None:
        return _run_error("Upload a video first.", spec_text, root, selected_spec, baseline)

    audio_path = _as_path(audio_file)
    upload = _as_path(spec_upload)
    selected_name = selected_spec

    try:
        if upload is not None:
            saved = save_uploaded_spec(upload.read_text(encoding="utf-8"), upload.name, root)
            spec, spec_text, selected_name = saved.spec, saved.text, saved.path.name
            reference, generated = "spec", False
        elif spec_text.strip():
            if selected_spec == NEW_SPEC:
                saved = save_new_spec(spec_text, new_filename, root)
                selected_name = saved.path.name
            else:
                saved = save_existing_spec(spec_text, selected_spec, root)
                selected_name = selected_spec
            spec, spec_text = saved.spec, saved.text
            reference, generated = "spec", False
        elif process_text.strip():
            generated_text = generate_spec_text(
                process_text,
                client=_client_key(client),
                cassette_path=_as_path(cassette),
            )
            saved = save_new_spec(generated_text, new_filename, root)
            spec, spec_text, selected_name = saved.spec, saved.text, saved.path.name
            reference, generated = "process", True
        else:
            spec, reference, generated = None, "none", False

        if reference == "none" and not listen_value and audio_path is None:
            return _run_error(
                "Choose a reference (process/spec) or enable a speech source.",
                spec_text,
                root,
                selected_spec,
                baseline,
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
        return _run_error(f"{type(exc).__name__}: {exc}", spec_text, root, selected_spec, baseline)

    if result.error is not None:
        return _run_error(result.error, spec_text, root, selected_spec, baseline)

    return _run_success(result, spec_text, root, selected_name)


def _stage_callback(progress: gr.Progress) -> Any:
    seen = {"count": 0}

    def on_stage(stage: str) -> None:
        seen["count"] += 1
        progress(min(0.95, seen["count"] / 14), desc=stage.replace("_", " "))

    return on_stage


def _run_error(
    message: str,
    spec_text: str,
    specs_dir: Path,
    selected_spec: str,
    baseline: str,
) -> tuple[Any, ...]:
    return (
        f"**error**\n\n{message}",
        [],
        [],
        "",
        spec_text,
        "",
        _history_value(()),
        dropdown_update(specs_dir, selected_spec),
        gr.update(),
        baseline,
        gr.update(),
        gr.update(),
        gr.update(),
        validation_message(spec_text),
    )


def _run_success(
    result: UiRunResult,
    spec_text: str,
    specs_dir: Path,
    selected_name: str,
) -> tuple[Any, ...]:
    status = f"**{result.status}** · run `{result.run_id}` · {len(result.keyframes)} keyframes"
    return (
        status,
        [list(item) for item in result.keyframes],
        list(result.flagged),
        result.assertions_json,
        result.spec_yaml or spec_text,
        result.report_markdown,
        _history_value(result.history),
        dropdown_update(specs_dir, selected_name),
        gr.update(visible=False, value=""),
        result.spec_yaml or spec_text,
        gr.update(interactive=False),
        gr.update(interactive=False),
        gr.update(interactive=delete_enabled(selected_name)),
        "",
    )


def build_ui() -> gr.Blocks:
    specs_dir = Settings().specs_dir
    choices = spec_choices(specs_dir)
    selected = initial_choice(specs_dir)
    initial_yaml = initial_spec_text(specs_dir)
    is_new = selected == NEW_SPEC

    with gr.Blocks(title="InsightScope-VLA") as demo:
        gr.Markdown(
            "# InsightScope-VLA\n"
            "Audit what a camera saw against what was said or planned. "
            "All routing goes through the same pipeline as the CLI."
        )

        baseline = gr.State(initial_yaml)

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
                    label="Audit spec (specs/)",
                    choices=choices,
                    value=selected,
                )
                new_filename = gr.Textbox(
                    label="New spec filename",
                    placeholder="brew_tea.yaml",
                    value="",
                    visible=is_new,
                )
                spec_text = gr.Textbox(
                    label="Audit spec (editable YAML)",
                    lines=14,
                    value=initial_yaml,
                )
                validation = gr.Markdown("")
                with gr.Row():
                    save_spec = gr.Button("Save Spec", interactive=False)
                    delete_spec = gr.Button(
                        "Delete Spec",
                        interactive=delete_enabled(selected),
                    )
                    generate = gr.Button("Generate Spec", interactive=False)
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

        editor_outputs = [
            spec_text,
            spec_choice,
            new_filename,
            baseline,
            generate,
            save_spec,
            delete_spec,
            validation,
            status,
        ]

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
        spec_choice.change(on_choice, [spec_choice, process_text], editor_outputs)
        new_filename.change(
            on_new_filename,
            [new_filename, spec_choice, process_text, spec_text, baseline],
            [generate, save_spec],
        )
        process_text.change(
            on_process,
            [process_text, spec_choice, new_filename],
            [generate],
        )
        spec_text.change(
            on_spec_text,
            [spec_text, spec_choice, baseline, new_filename],
            [validation, save_spec],
        )
        generate.click(
            on_generate,
            [process_text, client, cassette, spec_choice, new_filename, baseline],
            editor_outputs,
        )
        save_spec.click(
            on_save,
            [spec_text, spec_choice, baseline, new_filename],
            editor_outputs,
        )
        delete_spec.click(
            on_delete,
            [spec_choice, process_text, baseline],
            editor_outputs,
        )
        spec_upload.change(
            on_spec_upload,
            [spec_upload, baseline],
            editor_outputs,
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
                new_filename,
                client,
                cassette,
                omissions,
                baseline,
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
                new_filename,
                baseline,
                generate,
                save_spec,
                delete_spec,
                validation,
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
