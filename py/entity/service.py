"""Register-first entity resolution and corporate-tree safety checks."""

from __future__ import annotations

from .fetch import EntityFetch
from .models import (
    EntityRecord,
    RegisterId,
    RegisterType,
    ResolutionError,
    ResolutionResult,
    ResolutionWarning,
    WarningSeverity,
)


class EntityResolutionService:
    """Resolve an input to the terminal parent without guessing corporate scope."""

    def __init__(self, fetcher: EntityFetch) -> None:
        self._fetcher = fetcher

    def resolve(self, query: str) -> ResolutionResult:
        candidates = self._fetcher.lookup(query)
        if not candidates:
            raise ResolutionError(f"No register-backed candidate for {query!r}")
        if len(candidates) != 1:
            raise ResolutionError(
                f"Ambiguous register-backed candidates for {query!r}: "
                + ", ".join(candidate.display for candidate in candidates)
            )

        discovered = self._require_record(candidates[0])
        path, target = self._walk_to_terminal_parent(discovered)
        warnings = self._validate_path(discovered, path)
        subsidiaries = list(self._fetcher.children_of(target.register))

        if discovered.register != target.register:
            warnings.append(
                ResolutionWarning(
                    code="IMPRESSUM_ENTITY_NOT_GROUP",
                    severity=WarningSeverity.ADVISORY,
                    entity=discovered.register,
                    message=(
                        f"{discovered.legal_name} is a subsidiary of the resolved group "
                        f"{target.legal_name}; do not use the Impressum entity as the target."
                    ),
                )
            )

        return ResolutionResult(
            query=query,
            discovered=discovered,
            target=target,
            terminal_parent=target,
            upward_path=[record.register for record in path],
            subsidiaries=subsidiaries,
            warnings=warnings,
        )

    def _walk_to_terminal_parent(self, start: EntityRecord) -> tuple[list[EntityRecord], EntityRecord]:
        path = [start]
        seen = {start.register}
        current = start
        while (parent_register := self._derive_parent_register(current)) is not None:
            if parent_register in seen:
                raise ResolutionError(f"Corporate-tree cycle at {parent_register.display}")
            current = self._require_record(parent_register)
            seen.add(current.register)
            path.append(current)
        return path, current

    @staticmethod
    def _derive_parent_register(entity: EntityRecord) -> RegisterId | None:
        """Derive a parent solely from raw Gesellschafterliste entries.

        A natural person is not a corporate parent.  More than one distinct
        corporate shareholder is intentionally ambiguous: choosing one would
        invent a group tree that the register evidence does not establish.
        """
        corporate_holders = {
            entry.shareholder_register
            for entry in entity.shareholder_entries
            if entry.shareholder_register is not None
        }
        if not corporate_holders:
            return None
        if len(corporate_holders) > 1:
            identities = ", ".join(holder.display for holder in sorted(corporate_holders, key=lambda item: item.display))
            raise ResolutionError(
                f"Ambiguous corporate parents in Gesellschafterliste for {entity.register.display}: {identities}"
            )
        return next(iter(corporate_holders))

    def _validate_path(self, discovered: EntityRecord, path: list[EntityRecord]) -> list[ResolutionWarning]:
        warnings: list[ResolutionWarning] = []
        terminal = path[-1]
        for entity in path:
            expected_type = self._expected_register_type(entity.legal_form)
            if expected_type is not None and entity.register.register_type is not expected_type:
                warnings.append(
                    ResolutionWarning(
                        code="LEGAL_FORM_REGISTER_TYPE_MISMATCH",
                        severity=WarningSeverity.HARD,
                        entity=entity.register,
                        message=(
                            f"{entity.legal_name} has legal form {entity.legal_form!r} but "
                            f"is registered as {entity.register.register_type.value}; expected "
                            f"{expected_type.value}."
                        ),
                    )
                )

        if (
            discovered.files_konzernabschluss
            and discovered.register.register_type is RegisterType.HRB
            and self._expected_register_type(terminal.legal_form) is RegisterType.HRA
        ):
            warnings.append(
                ResolutionWarning(
                    code="CONSOLIDATED_FILER_PARENT_MISMATCH",
                    severity=WarningSeverity.HARD,
                    entity=discovered.register,
                    message=(
                        f"Konzernabschluss filer {discovered.register.display} is HRB while "
                        f"the terminal operating parent is {terminal.register.display} ({terminal.legal_form})."
                    ),
                )
            )
        return warnings

    def _require_record(self, register: RegisterId) -> EntityRecord:
        record = self._fetcher.get(register)
        if record is None:
            raise ResolutionError(f"Missing registry record for {register.display}")
        return record

    @staticmethod
    def _expected_register_type(legal_form: str) -> RegisterType | None:
        form = legal_form.casefold()
        if "kg" in form or "ohg" in form or "eg" in form:
            return RegisterType.HRA
        if "gmbh" in form or "ag" in form or "se" in form:
            return RegisterType.HRB
        return None
