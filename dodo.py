import glob
import shutil
from doit.tools import create_folder

DOIT_CONFIG = dict(default_tasks=["app"])


def task_gitclean():
    """Clean all generated files not tracked by GIT."""
    return dict(actions=["git clean -xdf -e .venv"])


def task_pot():
    """Re-create .pot ."""
    return dict(
        actions=["pybabel extract -o covid.pot covid"],
        file_dep=glob.glob("covid/*.py"),
        targets=["covid.pot"],
    )


def task_po():
    """Update translations."""
    return dict(
        actions=["pybabel update -D covid -d po -i covid.pot"],
        file_dep=["covid.pot"],
        targets=["po/ru/LC_MESSAGES/covid.po"],
    )


def task_mo():
    """Compile translations."""
    return dict(
        actions=[
            (create_folder, ["covid/ru/LC_MESSAGES"]),
            "pybabel compile -D covid -l ru -i po/ru/LC_MESSAGES/covid.po -d covid",
        ],
        file_dep=["po/ru/LC_MESSAGES/covid.po"],
        targets=["covid/ru/LC_MESSAGES/covid.mo"],
    )


def task_copyresources():
    """Copy font."""
    return dict(
        actions=[
            (
                shutil.copy,
                ["resources/OpenSans-Regular.ttf", "covid/OpenSans-Regular.ttf"],
            )
        ]
    )


def task_app():
    """Run application."""
    return dict(actions=["python -m covid"], task_dep=["mo", "copyresources"])


def task_sdist():
    """Create source distribution."""
    return dict(actions=["python -m build -s"], task_dep=["gitclean"])


def task_wheel():
    """Create binary wheel distribution."""
    return dict(actions=["python -m build -w"], task_dep=["mo", "copyresources"])
