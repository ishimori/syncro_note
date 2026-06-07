import synchroni_note


def test_import_and_version() -> None:
    assert isinstance(synchroni_note.__version__, str)
    assert synchroni_note.__version__
