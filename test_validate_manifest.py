#!/usr/bin/env python3
"""Regression tests for manifest invariants."""

import copy
import json
import unittest
from pathlib import Path

from validate_manifest import (
    Report,
    validate_component,
    validate_cross_section,
    validate_wcp_identity,
)


MANIFEST = json.loads(Path(__file__).with_name("content_manifest.json").read_text())


class ManifestValidationTest(unittest.TestCase):
    def test_component_size_is_required(self) -> None:
        entry = copy.deepcopy(MANIFEST["components"]["rootfs"])
        entry.pop("size")
        report = Report()

        validate_component(report, "rootfs", entry)

        self.assertTrue(any("size is required" in error for error in report.errors))

    def test_boolean_is_not_a_valid_size(self) -> None:
        entry = copy.deepcopy(MANIFEST["components"]["rootfs"])
        entry["size"] = True
        report = Report()

        validate_component(report, "rootfs", entry)

        self.assertTrue(any("size is required" in error for error in report.errors))

    def test_cross_section_duplicate_is_rejected_even_when_pins_match(self) -> None:
        components = copy.deepcopy(MANIFEST["components"])
        duplicate = copy.deepcopy(components["rootfs"])
        report = Report()

        validate_cross_section(report, components, [duplicate])

        self.assertTrue(
            any("exactly one section" in error for error in report.errors)
        )

    def test_wcp_version_must_match_identity_triplet(self) -> None:
        entry = copy.deepcopy(MANIFEST["components"]["wine"])
        # Must diverge from whatever verCode the live pin currently uses
        # (hardcoding 0 broke once wine was published with verCode=0).
        entry["verCode"] = int(entry["verCode"]) + 1
        report = Report()

        validate_wcp_identity(report, "components.wine", entry)

        self.assertTrue(any("contentType-verName-verCode" in error for error in report.errors))

    def test_live_wine_pin_identity_is_consistent(self) -> None:
        report = Report()
        validate_wcp_identity(report, "components.wine", MANIFEST["components"]["wine"])
        self.assertEqual(report.errors, [])



if __name__ == "__main__":
    unittest.main()
