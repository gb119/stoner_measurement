"""Discovery and editing support for reusable Curve Fit function modules."""

from __future__ import annotations

import ast
import keyword
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qtpy.QtCore import Qt, Signal
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from stoner_measurement.resources import user_config_root
from stoner_measurement.ui.editor_widget import EditorWidget

logger = logging.getLogger(__name__)

STANDARD_FUNCTIONS_PACKAGE = "stoner_measurement.plugins.transform.standard_functions"
USER_FUNCTIONS_PACKAGE = "user_functions"


def _is_valid_module_part(part: str) -> bool:
    """Return whether *part* can be used in a dotted Python module name."""
    return part.isidentifier() and not keyword.iskeyword(part)


@dataclass(frozen=True)
class FitFunctionModule:
    """One valid fitting-function module discovered on disk."""

    collection: str
    module_name: str
    path: Path
    display_parts: tuple[str, ...]
    docstring: str = ""

    def source(self) -> str:
        """Return the complete Python source for this module."""
        return self.path.read_text(encoding="utf-8")


def standard_functions_root() -> Path:
    """Return the bundled standard fitting-functions package directory."""
    return Path(__file__).with_name("standard_functions")


def user_functions_root() -> Path:
    """Return the per-user fitting-functions package directory."""
    return user_config_root() / USER_FUNCTIONS_PACKAGE


def _positional_parameter_count(node: ast.FunctionDef) -> int:
    """Return the number of positional parameters declared by *node*."""
    return len(node.args.posonlyargs) + len(node.args.args)


def validate_fit_function_source(source: str) -> str | None:
    """Return an exclusion reason, or ``None`` when *source* is a valid module.

    A module must define a top-level ``fit`` function with at least two
    positional parameters. If it defines top-level ``p0``, that function must
    take exactly two positional parameters.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"Syntax error on line {exc.lineno}: {exc.msg}"

    for index, node in enumerate(tree.body):
        is_docstring = (
            index == 0
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
        if not is_docstring and not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            return (
                "Only imports, function definitions, and an optional module "
                "docstring are allowed at module level."
            )

    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    fit_node = functions.get("fit")
    if fit_node is None:
        return "Module does not define a top-level fit() function."
    if _positional_parameter_count(fit_node) < 2:
        return "fit() must take at least two positional parameters."

    p0_node = functions.get("p0")
    if p0_node is not None and _positional_parameter_count(p0_node) != 2:
        return "p0() must take exactly two positional parameters."
    return None


def _discover_collection(
    root: Path,
    collection: str,
    package_name: str,
) -> list[FitFunctionModule]:
    """Discover valid fitting-function modules beneath one package root."""
    if not root.is_dir():
        return []

    modules: list[FitFunctionModule] = []
    for path in sorted(root.rglob("*.py"), key=lambda item: str(item).casefold()):
        relative = path.relative_to(root)
        if path.name == "__init__.py" or any(
            not _is_valid_module_part(part) for part in relative.with_suffix("").parts
        ):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            logger.warning("Unable to read Curve Fit function module %s: %s", path, exc)
            continue
        exclusion = validate_fit_function_source(source)
        if exclusion is not None:
            logger.debug("Excluded Curve Fit function module %s: %s", path, exclusion)
            continue
        parts = relative.with_suffix("").parts
        modules.append(
            FitFunctionModule(
                collection=collection,
                module_name=".".join((package_name, *parts)),
                path=path,
                display_parts=parts,
                docstring=ast.get_docstring(ast.parse(source), clean=True) or "",
            )
        )
    return modules


def discover_fit_function_modules(
    *,
    standard_root: Path | None = None,
    user_root: Path | None = None,
) -> list[FitFunctionModule]:
    """Return valid bundled and user fitting-function modules."""
    standard_root = standard_root or standard_functions_root()
    user_root = user_root or user_functions_root()
    return [
        *_discover_collection(
            standard_root,
            "Standard functions",
            STANDARD_FUNCTIONS_PACKAGE,
        ),
        *_discover_collection(user_root, "User functions", USER_FUNCTIONS_PACKAGE),
    ]


def prepare_user_module_path(
    selected_path: str | Path, root: Path | None = None
) -> tuple[Path, str]:
    """Validate a user module destination and create its package directories.

    Missing ``__init__.py`` files are created from the user-functions root down
    to the selected module's parent directory.
    """
    root = (root or user_functions_root()).resolve()
    selected = Path(selected_path)
    if selected.suffix == "":
        selected = selected.with_suffix(".py")
    if selected.suffix.lower() != ".py":
        raise ValueError("Fit function modules must use the .py extension.")

    target = selected.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Select a file inside {root}.") from exc

    module_parts = relative.with_suffix("").parts
    if not module_parts or any(not _is_valid_module_part(part) for part in module_parts):
        raise ValueError("Every package and module name must be a valid Python identifier.")
    if module_parts[-1] == "__init__":
        raise ValueError("Select a module file rather than __init__.py.")

    target.parent.mkdir(parents=True, exist_ok=True)
    package_dir = root
    package_dirs = [root]
    for part in relative.parent.parts:
        package_dir /= part
        package_dirs.append(package_dir)
    for directory in package_dirs:
        init_file = directory / "__init__.py"
        if not init_file.exists():
            init_file.write_text("", encoding="utf-8")

    return target, ".".join((USER_FUNCTIONS_PACKAGE, *module_parts))


class FitFunctionTab(QWidget):
    """Fit Function tab that caps its editor at 25 lines or two-thirds height."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._editor: EditorWidget | None = None

    def set_editor(self, editor: EditorWidget) -> None:
        """Set the editor whose height this tab manages."""
        self._editor = editor

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Recalculate the bounded editor height when the tab is resized."""
        super().resizeEvent(event)
        if self._editor is None:
            return
        line_height = self._editor.fontMetrics().lineSpacing()
        document_padding = round(self._editor.document().documentMargin() * 2)
        frame_padding = self._editor.frameWidth() * 2
        twenty_five_lines = line_height * 25 + document_padding + frame_padding
        two_thirds = max(line_height, event.size().height() * 2 // 3)
        self._editor.setFixedHeight(min(twenty_five_lines, two_thirds))


class FitFunctionLibraryWidget(QWidget):
    """Tree browser for bundled and per-user fitting-function modules."""

    module_activated = Signal(str)

    def __init__(
        self,
        editor: EditorWidget,
        parent: QWidget | None = None,
        *,
        standard_root: Path | None = None,
        user_root: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._standard_root = standard_root
        self._user_root = user_root
        self._module_items: dict[str, QTreeWidgetItem] = {}
        self._modules: dict[str, FitFunctionModule] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Fitting function library", self))

        self.tree = QTreeWidget(self)
        self.tree.setObjectName("fitFunctionLibraryTree")
        self.tree.setHeaderHidden(True)
        self.tree.setAccessibleName("Fitting function library")

        button_layout = QHBoxLayout()
        self.load_button = QPushButton("Load", self)
        self.load_button.setObjectName("loadFitFunctionButton")
        self.load_button.setEnabled(False)
        self.save_button = QPushButton("Save…", self)
        self.save_button.setObjectName("saveFitFunctionButton")
        self.refresh_button = QPushButton("Refresh", self)
        self.refresh_button.setObjectName("refreshFitFunctionLibraryButton")
        button_layout.addWidget(self.load_button)
        button_layout.addWidget(self.save_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.refresh_button)
        layout.addLayout(button_layout)
        layout.addWidget(self.tree, 1)

        self.tree.itemSelectionChanged.connect(self._update_load_button)
        self.tree.itemDoubleClicked.connect(self._load_item)
        self.load_button.clicked.connect(self.load_selected)
        self.save_button.clicked.connect(self.save_current)
        self.refresh_button.clicked.connect(self.refresh)
        self.refresh()

    def _selected_module(self) -> FitFunctionModule | None:
        """Return the selected leaf's module descriptor, if any."""
        item = self.tree.currentItem()
        if item is None:
            return None
        module_name = item.data(0, Qt.ItemDataRole.UserRole)
        return self._modules.get(module_name) if isinstance(module_name, str) else None

    def _update_load_button(self) -> None:
        """Enable Load only while a module leaf is selected."""
        self.load_button.setEnabled(self._selected_module() is not None)

    @staticmethod
    def _child_group(parent: QTreeWidgetItem, label: str) -> QTreeWidgetItem:
        """Return an existing named group child or append a new one."""
        for index in range(parent.childCount()):
            child = parent.child(index)
            if child.text(0) == label and child.data(0, Qt.ItemDataRole.UserRole) is None:
                return child
        child = QTreeWidgetItem([label])
        parent.addChild(child)
        return child

    def refresh(self) -> None:
        """Rescan both fitting-function packages and rebuild the tree."""
        self.tree.clear()
        self._module_items.clear()
        self._modules.clear()
        roots = {
            label: QTreeWidgetItem([label]) for label in ("Standard functions", "User functions")
        }
        for root_item in roots.values():
            root_item.setFlags(root_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.tree.addTopLevelItem(root_item)
        roots["Standard functions"].setToolTip(
            0, str(self._standard_root or standard_functions_root())
        )
        roots["User functions"].setToolTip(0, str(self._user_root or user_functions_root()))

        modules = discover_fit_function_modules(
            standard_root=self._standard_root,
            user_root=self._user_root,
        )
        for module in modules:
            parent = roots[module.collection]
            for part in module.display_parts[:-1]:
                parent = self._child_group(parent, part)
            leaf = QTreeWidgetItem([module.display_parts[-1]])
            leaf.setData(0, Qt.ItemDataRole.UserRole, module.module_name)
            leaf.setToolTip(0, module.docstring or str(module.path))
            parent.addChild(leaf)
            self._module_items[module.module_name] = leaf
            self._modules[module.module_name] = module

        self.tree.expandAll()
        self._update_load_button()

    def _load_item(self, item: QTreeWidgetItem, _column: int) -> None:
        """Load a double-clicked module leaf."""
        module_name = item.data(0, Qt.ItemDataRole.UserRole)
        module = self._modules.get(module_name) if isinstance(module_name, str) else None
        if module is not None:
            self._load_module(module)

    def _load_module(self, module: FitFunctionModule) -> None:
        """Copy one module's complete source into the editor."""
        try:
            source = module.source()
        except (OSError, UnicodeError) as exc:
            QMessageBox.critical(self, "Unable to load fit function", str(exc))
            return
        self._editor.set_text(source)
        self.module_activated.emit(module.module_name)

    def load_selected(self) -> None:
        """Load the selected fitting-function module into the editor."""
        module = self._selected_module()
        if module is not None:
            self._load_module(module)

    def save_current(self) -> None:
        """Save the editor source as a module beneath ``user_functions``."""
        source = self._editor.text()
        exclusion = validate_fit_function_source(source)
        if exclusion is not None:
            QMessageBox.warning(self, "Invalid fit function", exclusion)
            return

        root = self._user_root or user_functions_root()
        try:
            root.mkdir(parents=True, exist_ok=True)
            init_file = root / "__init__.py"
            if not init_file.exists():
                init_file.write_text("", encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Unable to save fit function", str(exc))
            return
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Save fitting function",
            str(root),
            "Python modules (*.py)",
        )
        if not selected:
            return
        try:
            target, module_name = prepare_user_module_path(selected, root)
            target.write_text(source, encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            QMessageBox.warning(self, "Unable to save fit function", str(exc))
            return

        self.refresh()
        item = self._module_items.get(module_name)
        if item is not None:
            self.tree.setCurrentItem(item)
        self.module_activated.emit(module_name)


def module_execution_context(module_name: str) -> dict[str, Any]:
    """Return module globals needed for package-relative imports."""
    if not module_name:
        return {"__name__": "fit_code", "__package__": None}
    if module_name == USER_FUNCTIONS_PACKAGE or module_name.startswith(
        f"{USER_FUNCTIONS_PACKAGE}."
    ):
        import_root = str(user_functions_root().parent)
        if import_root not in sys.path:
            sys.path.insert(0, import_root)
    context: dict[str, Any] = {
        "__name__": module_name,
        "__package__": module_name.rpartition(".")[0] or None,
    }
    prefixes = (
        (STANDARD_FUNCTIONS_PACKAGE, standard_functions_root()),
        (USER_FUNCTIONS_PACKAGE, user_functions_root()),
    )
    for package_name, root in prefixes:
        if module_name.startswith(f"{package_name}."):
            relative_parts = module_name.removeprefix(f"{package_name}.").split(".")
            source_path = root.joinpath(*relative_parts).with_suffix(".py")
            if source_path.is_file():
                context["__file__"] = str(source_path)
            break
    return context
