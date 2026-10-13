"""Business callers use the single stable identity-error catalogue."""

import ast
from pathlib import Path

import ekumidayomi

_GENERIC_ERRORS = {
    "ApplicationError",
    "AuthenticationError",
    "ConflictError",
    "DependencyUnavailableError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitError",
    "ValidationError",
}


def test_identity_modules_do_not_import_or_construct_generic_business_errors() -> None:
    assert ekumidayomi.__file__ is not None
    root = Path(ekumidayomi.__file__).resolve().parent
    files = [
        *root.joinpath("auth").rglob("*.py"),
        *root.joinpath("users").rglob("*.py"),
        root / "api/v1/auth.py",
        root / "api/v1/registration.py",
        root / "api/v1/admin.py",
        root / "api/v1/customer_profile.py",
    ]
    errors_module = root / "users/errors.py"
    assert errors_module.is_file()

    for path in files:
        if path == errors_module:
            continue
        assert path.is_file(), f"Missing identity implementation: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "ekumidayomi.core.errors":
                    imported = {item.name for item in node.names}
                    assert not imported & (_GENERIC_ERRORS | {"*"}), str(path)
                if node.module == "ekumidayomi.users.errors":
                    assert all(item.name != "*" for item in node.names), str(path)
            if isinstance(node, ast.Import):
                assert all(item.name != "ekumidayomi.core.errors" for item in node.names), str(path)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                assert node.name not in {"denied", "rejected"}, str(path)
