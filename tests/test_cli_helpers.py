from naukri_assistant.cli import _clean_path_input


def test_clean_path_input_accepts_quoted_windows_paths() -> None:
    raw = '"C:\\Users\\Ganesh\\Downloads\\Ganesh_v_resume (6).pdf"'
    assert _clean_path_input(raw) == "C:\\Users\\Ganesh\\Downloads\\Ganesh_v_resume (6).pdf"

