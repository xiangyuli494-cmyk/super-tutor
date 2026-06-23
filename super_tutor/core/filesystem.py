"""File system module for the Forge engine.

Manages the six-zone isolated directory structure and provides
permission-aware file operations for the three AI roles.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class FileSystemError(Exception):
    """Base exception for filesystem module errors."""


class PermissionDeniedError(FileSystemError):
    """Raised when a role attempts an operation without sufficient permissions."""


class PathTraversalError(FileSystemError):
    """Raised when a path attempts to escape the project root."""


class InvalidZoneError(FileSystemError):
    """Raised when referencing a zone that does not exist."""


# ---------------------------------------------------------------------------
# FileSystem
# ---------------------------------------------------------------------------


class FileSystem:
    """Manages project file system with role-based access control.

    The six-zone layout isolates work by role, enforced through a write-permission
    matrix. Every role can read from any zone.  Only the zone owner may write to
    it (with ``artifacts`` shared as a common write area).

    Attributes:
        project_root: Absolute path to the project root directory.
        ZONES: The six zone names.
        WRITE_PERMISSIONS: Mapping of role name to list of writable zone names.
    """

    ZONES: list[str] = ["constitution", "sandbox", "src", "test", "review", "artifacts"]

    WRITE_PERMISSIONS: dict[str, list[str]] = {
        "claude-a": ["constitution", "review", "artifacts"],
        "codex": ["sandbox", "artifacts"],
        "claude-b": ["test", "src", "artifacts"],
    }

    def __init__(self, project_root: str) -> None:
        """Initialize the FileSystem for a given project.

        Args:
            project_root: Absolute or relative path to the project root directory.
                It will be resolved to an absolute path immediately.
        """
        self.project_root: Path = Path(project_root).resolve()

    # ------------------------------------------------------------------
    # Directory operations
    # ------------------------------------------------------------------

    def init_project_structure(self) -> None:
        """Create the six zone directories and seed initial files from templates.

        Creates each zone directory under ``project_root`` if it does not already
        exist.  If the engine ships a ``templates/project-structure/`` directory,
        its contents are copied into the project root (existing files are not
        overwritten).

        Raises:
            OSError: If a directory cannot be created or files cannot be copied.
        """
        for zone in self.ZONES:
            zone_path = self.project_root / zone
            zone_path.mkdir(parents=True, exist_ok=True)

        # Copy template files if the template directory exists.
        engine_root = Path(__file__).resolve().parent.parent  # forge-engine/
        template_dir = engine_root / "templates" / "project-structure"
        if template_dir.is_dir():
            self._copy_template_dir(template_dir, self.project_root)

    def ensure_zone(self, zone: str) -> Path:
        """Ensure a zone directory exists and return its absolute path.

        Args:
            zone: Zone name (must be one of ``ZONES``).

        Returns:
            Absolute ``Path`` to the zone directory.

        Raises:
            InvalidZoneError: If *zone* is not a recognized zone name.
        """
        if zone not in self.ZONES:
            raise InvalidZoneError(
                f"Unknown zone '{zone}'. Valid zones: {', '.join(self.ZONES)}"
            )
        zone_path = self.project_root / zone
        zone_path.mkdir(parents=True, exist_ok=True)
        return zone_path

    # ------------------------------------------------------------------
    # Permission checks
    # ------------------------------------------------------------------

    def can_write(self, role: str, path: str) -> bool:
        """Check whether *role* has permission to write to *path*.

        Args:
            role: Role name (``claude-a``, ``codex``, or ``claude-b``).
            path: Relative path within the project.

        Returns:
            ``True`` if the role may write to the zone that contains *path*.
        """
        try:
            zone = self.find_zone(path)
        except InvalidZoneError:
            return False
        allowed_zones = self.WRITE_PERMISSIONS.get(role, [])
        return zone in allowed_zones

    def can_read(self, role: str, path: str) -> bool:
        """Check whether *role* has permission to read from *path*.

        All roles are permitted to read from every zone (the write restriction
        is the primary security boundary; transparency across zones is
        essential for review and auditing).

        Args:
            role: Role name.
            path: Relative path within the project.

        Returns:
            Always ``True`` provided the path is inside the project root.
        """
        try:
            self._resolve_path(path)
        except PathTraversalError:
            return False
        return True

    def guard_write(self, role: str, path: str) -> None:
        """Raise ``PermissionDeniedError`` if *role* cannot write to *path*.

        Args:
            role: Role name.
            path: Relative path within the project.

        Raises:
            PermissionDeniedError: If the role lacks write permission for the
                target zone.
        """
        if not self.can_write(role, path):
            zone = self.find_zone(path)
            raise PermissionDeniedError(
                f"Role '{role}' is not permitted to write to zone '{zone}' "
                f"(path: {path}). Allowed zones: "
                f"{self.WRITE_PERMISSIONS.get(role, [])}"
            )

    # ------------------------------------------------------------------
    # File operations (permission-aware)
    # ------------------------------------------------------------------

    def read_file(
        self,
        role: str,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """Read the contents of a file, optionally slicing by line range.

        Args:
            role: Role requesting the read.
            path: Relative path to the file within the project.
            start_line: 1-based inclusive start line (``None`` means first line).
            end_line: 1-based inclusive end line (``None`` means last line).

        Returns:
            The file content as a string.  Line-range slicing preserves the
            original line endings.

        Raises:
            FileNotFoundError: If *path* does not exist.
            PathTraversalError: If *path* escapes the project root.
            IsADirectoryError: If *path* points to a directory.
        """
        resolved = self._resolve_path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if resolved.is_dir():
            raise IsADirectoryError(f"Path is a directory, not a file: {path}")

        with open(resolved, "r", encoding="utf-8") as fh:
            lines = fh.readlines()

        # Apply line-range slicing.
        total = len(lines)
        sl = max(1, start_line) - 1 if start_line is not None else 0
        el = min(total, end_line) if end_line is not None else total
        if sl < 0:
            sl = 0
        if el > total:
            el = total
        return "".join(lines[sl:el])

    def write_file(self, role: str, path: str, content: str) -> None:
        """Write *content* to *path*, enforcing role write permissions.

        Automatically creates parent directories if they do not exist.

        Args:
            role: Role requesting the write.
            path: Relative path to the target file.
            content: Text content to write.

        Raises:
            PermissionDeniedError: If *role* lacks write permission.
            PathTraversalError: If *path* escapes the project root.
        """
        self.guard_write(role, path)
        resolved = self._resolve_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(content)

    def list_dir(self, role: str, path: str = "") -> list[dict[str, Any]]:
        """List the contents of a directory.

        Args:
            role: Role requesting the listing.
            path: Relative path to the directory (empty string = project root).

        Returns:
            List of entries, each a dict with keys ``name``, ``type``
            (``"file"`` or ``"directory"``), and ``size`` (bytes; 0 for
            directories).

        Raises:
            FileNotFoundError: If the directory does not exist.
            PathTraversalError: If *path* escapes the project root.
        """
        resolved = self._resolve_path(path) if path else self.project_root
        if not resolved.exists():
            raise FileNotFoundError(f"Directory not found: {path or '.'}")
        if not resolved.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {path or '.'}")

        entries: list[dict[str, Any]] = []
        try:
            for entry in sorted(resolved.iterdir()):
                info: dict[str, Any] = {
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": 0 if entry.is_dir() else entry.stat().st_size,
                }
                entries.append(info)
        except PermissionError:
            raise PermissionDeniedError(
                f"Role '{role}' cannot read directory: {path or '.'}"
            )
        return entries

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def migrate_to_src(self, sandbox_module: str) -> None:
        """Copy a sandbox module into the ``src`` zone for integration.

        This is the **only** path by which code enters ``src``.  The caller
        (orchestrator) is expected to verify that the invoking role
        (``claude-b``) has the appropriate permissions before calling this
        method.

        The source ``sandbox/{sandbox_module}/`` is copied recursively into
        ``src/{sandbox_module}/``.  Any files already present in the
        destination are overwritten.

        Args:
            sandbox_module: The module directory name inside ``sandbox/``.

        Raises:
            ValueError: If *sandbox_module* contains ``/``, ``\\``, or ``..``.
            FileNotFoundError: If the sandbox module does not exist.
            OSError: If the copy operation fails.
        """
        # P1: Defensive validation -- reject path traversal characters.
        if "/" in sandbox_module or "\\" in sandbox_module or ".." in sandbox_module:
            raise ValueError(
                f"sandbox_module must be a plain directory name, "
                f"got: {sandbox_module!r}"
            )

        src_dir = self.project_root / "sandbox" / sandbox_module
        dst_dir = self.project_root / "src" / sandbox_module

        if not src_dir.is_dir():
            raise FileNotFoundError(
                f"Sandbox module not found: sandbox/{sandbox_module}"
            )

        # Remove destination if it already exists so copytree can proceed.
        if dst_dir.exists():
            shutil.rmtree(dst_dir)

        shutil.copytree(str(src_dir), str(dst_dir))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path safely, preventing directory-traversal attacks.

        The path is joined to ``project_root`` and resolved.  If the resolved
        absolute path lies outside ``project_root`` (e.g. via ``../``
        sequences), a ``PathTraversalError`` is raised.

        Args:
            path: Relative path within the project.

        Returns:
            Absolute, resolved ``Path`` object.

        Raises:
            PathTraversalError: If the resolved path escapes ``project_root``.
        """
        # Normalize: strip leading slashes/backslashes so the path is always
        # treated as relative to project_root.
        cleaned = path.lstrip(os.sep).lstrip("/")
        resolved = (self.project_root / cleaned).resolve()

        # Ensure the resolved path is still a descendant of project_root.
        try:
            resolved.relative_to(self.project_root)
        except ValueError:
            raise PathTraversalError(
                f"Path traversal detected: '{path}' resolves to '{resolved}' "
                f"which is outside project root '{self.project_root}'."
            )
        return resolved

    def _copy_template_dir(self, src: Path, dst: Path) -> None:
        """Recursively copy template files, skipping files that already exist.

        Args:
            src: Source template directory.
            dst: Destination directory (project root).
        """
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                self._copy_template_dir(item, target)
            else:
                if not target.exists():
                    shutil.copy2(str(item), str(target))

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def get_file_tree(self, include_hidden: bool = False) -> dict[str, Any]:
        """Build a nested dictionary representing the entire project file tree.

        Hidden files and directories (those whose name starts with ``.``) are
        excluded from the tree by default.  Set *include_hidden* to ``True`` to
        include them.

        Args:
            include_hidden: If ``True``, include files and directories whose
                name starts with a dot.

        Returns:
            A tree node with keys ``name``, ``type`` (``"directory"`` or
            ``"file"``), ``size`` (bytes), ``children`` (list of nodes; only
            for directories), and ``zone`` (zone name for top-level children
            only).
        """
        return self._build_tree_node(
            self.project_root, is_root=True, include_hidden=include_hidden
        )

    def _build_tree_node(
        self, path: Path, is_root: bool = False, include_hidden: bool = False
    ) -> dict[str, Any]:
        """Recursively build a tree node for the given path.

        Hidden entries are skipped unless *include_hidden* is ``True``.
        """
        if path.is_file():
            return {
                "name": path.name,
                "type": "file",
                "size": path.stat().st_size,
            }

        # Directory node.
        children: list[dict[str, Any]] = []
        try:
            for entry in sorted(path.iterdir()):
                if not include_hidden and entry.name.startswith("."):
                    continue
                children.append(
                    self._build_tree_node(entry, include_hidden=include_hidden)
                )
        except PermissionError:
            pass  # Skip inaccessible entries.

        node: dict[str, Any] = {
            "name": path.name if not is_root else self.project_root.name,
            "type": "directory",
            "size": 0,
            "children": children,
        }
        # Tag top-level children with their zone.
        if is_root:
            node["zone"] = None  # root is not a zone
            for child in children:
                if child["name"] in self.ZONES:
                    child["zone"] = child["name"]
        return node

    def find_zone(self, path: str) -> str:
        """Determine which zone a path belongs to.

        The zone is the first path component (the top-level directory name
        under the project root).  The path is resolved safely before zone
        detection.

        Args:
            path: Relative path within the project.

        Returns:
            Zone name (one of ``ZONES``).

        Raises:
            InvalidZoneError: If the first path component is not a recognised
                zone name (including the case where the path is empty or is
                the project root itself).
            PathTraversalError: If *path* escapes the project root.
        """
        resolved = self._resolve_path(path)

        try:
            rel = resolved.relative_to(self.project_root)
        except ValueError:
            raise PathTraversalError(
                f"Path '{path}' is outside the project root."
            )

        parts = rel.parts
        if not parts:
            raise InvalidZoneError(
                f"Cannot determine zone for the project root: '{path}'"
            )

        zone = parts[0]
        if zone not in self.ZONES:
            raise InvalidZoneError(
                f"Path '{path}' is not inside any known zone. "
                f"First component '{zone}' is not one of {self.ZONES}."
            )
        return zone
