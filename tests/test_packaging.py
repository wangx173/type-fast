"""Exercise the spec's platform decisions without requiring PyInstaller."""

from pathlib import Path
from types import ModuleType, SimpleNamespace
import os
import runpy
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = compile((ROOT / "Type Fast.spec").read_text(encoding="utf-8"), "Type Fast.spec", "exec")


def run_spec(platform: str, product_version: str = "0.1.0") -> dict:
    constructors = {
        name: Mock(name=name)
        for name in ("Analysis", "PYZ", "EXE", "COLLECT", "BUNDLE")
    }
    constructors["Analysis"].return_value = SimpleNamespace(
        pure=[], zipped_data=[], scripts=[], binaries=[], datas=[],
    )
    versioninfo = ModuleType("PyInstaller.utils.win32.versioninfo")
    for name in (
        "FixedFileInfo", "StringFileInfo", "StringStruct", "StringTable",
        "VarFileInfo", "VarStruct", "VSVersionInfo",
    ):
        setattr(versioninfo, name, Mock(name=name))
    namespace = dict(constructors)
    with (
        patch("sys.platform", platform),
        patch("importlib.metadata.version", return_value=product_version) as metadata_version,
        patch.dict("sys.modules", {"PyInstaller.utils.win32.versioninfo": versioninfo}),
    ):
        exec(SPEC, namespace)
    return {
        **constructors, "namespace": namespace, "versioninfo": versioninfo,
        "metadata_version": metadata_version,
    }


class PackagingTests(unittest.TestCase):
    def test_packaged_smoke_mode_sets_offscreen_before_startup(self) -> None:
        with (
            patch("sys.argv", ["Type Fast.exe", "--smoke-test"]),
            patch.dict(os.environ, {}, clear=True),
            patch("type_fast.app.main") as main,
        ):
            main.return_value = 0
            with self.assertRaises(SystemExit) as exit:
                runpy.run_path(str(ROOT / "launch.py"), run_name="__main__")
            self.assertEqual(exit.exception.code, 0)
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "offscreen")
            main.assert_called_once_with(smoke_test=True)

    def test_normal_packaged_launch_preserves_qt_platform(self) -> None:
        with (
            patch("sys.argv", ["Type Fast.exe"]),
            patch.dict(os.environ, {"QT_QPA_PLATFORM": "existing"}, clear=True),
            patch("type_fast.app.main") as main,
        ):
            runpy.run_path(str(ROOT / "launch.py"), run_name="__main__")
            self.assertEqual(os.environ["QT_QPA_PLATFORM"], "existing")
            main.assert_called_once_with()

    def test_packaged_smoke_propagates_event_loop_exit_code(self) -> None:
        with (
            patch("sys.argv", ["Type Fast.exe", "--smoke-test"]),
            patch.dict(os.environ, {}, clear=True),
            patch("type_fast.app.main", return_value=3),
        ):
            with self.assertRaises(SystemExit) as exit:
                runpy.run_path(str(ROOT / "launch.py"), run_name="__main__")
            self.assertEqual(exit.exception.code, 3)

    def test_smoke_quits_only_after_window_initialization(self) -> None:
        from type_fast import app

        with (
            patch.object(app, "QApplication") as application,
            patch.object(app, "MainWindow") as window,
            patch.object(app, "QTimer") as timer,
            patch.object(app, "app_icon"),
        ):
            application.instance.return_value.exec.return_value = 0
            self.assertEqual(app.main(smoke_test=True), 0)
            window.return_value.summon.assert_called_once_with()
            timer.singleShot.assert_called_once_with(
                0, application.instance.return_value.quit,
            )
            application.instance.return_value.exec.assert_called_once_with()

    def test_smoke_initialization_failure_cannot_signal_success(self) -> None:
        from type_fast import app

        with (
            patch.object(app, "QApplication") as application,
            patch.object(app, "MainWindow", side_effect=ImportError("missing bundle")),
            patch.object(app, "QTimer") as timer,
            patch.object(app, "app_icon"),
        ):
            with self.assertRaisesRegex(ImportError, "missing bundle"):
                app.main(smoke_test=True)
            timer.singleShot.assert_not_called()
            application.instance.return_value.exec.assert_not_called()

    def test_normal_main_does_not_schedule_smoke_exit(self) -> None:
        from type_fast import app

        with (
            patch.object(app, "QApplication"),
            patch.object(app, "MainWindow"),
            patch.object(app, "QTimer") as timer,
            patch.object(app, "app_icon"),
        ):
            app.main()
            timer.singleShot.assert_not_called()

    def test_macos_bundle_options_are_preserved(self) -> None:
        result = run_spec("darwin")
        options = result["EXE"].call_args.kwargs
        self.assertTrue(options["argv_emulation"])
        self.assertFalse(options["console"])
        self.assertNotIn("icon", options)
        self.assertNotIn("version", options)
        result["metadata_version"].assert_not_called()
        bundle = result["BUNDLE"].call_args.kwargs
        self.assertEqual(bundle["name"], "Type Fast.app")
        self.assertEqual(bundle["icon"], "assets/icon/TypeFast.icns")
        self.assertEqual(bundle["info_plist"]["CFBundleVersion"], "0.1.0")
        self.assertIn("NSMicrophoneUsageDescription", bundle["info_plist"])

    def test_windows_build_is_windowed_one_folder_with_version(self) -> None:
        result = run_spec("win32", "2.3.4")
        options = result["EXE"].call_args.kwargs
        self.assertFalse(options["console"])
        self.assertFalse(options["argv_emulation"])
        self.assertTrue(options["exclude_binaries"])
        self.assertEqual(options["icon"], "assets/icon/TypeFast.ico")
        self.assertEqual(result["COLLECT"].call_args.kwargs["name"], "Type Fast")
        result["BUNDLE"].assert_not_called()
        result["metadata_version"].assert_called_once_with("type-fast")
        versioninfo = result["versioninfo"]
        self.assertEqual(versioninfo.FixedFileInfo.call_args.kwargs["filevers"], (2, 3, 4, 0))
        self.assertEqual(versioninfo.FixedFileInfo.call_args.kwargs["prodvers"], (2, 3, 4, 0))
        values = [call.args for call in versioninfo.StringStruct.call_args_list]
        self.assertIn(("ProductName", "Type Fast"), values)
        self.assertIn(("ProductVersion", "2.3.4"), values)
        self.assertIn(("OriginalFilename", "Type Fast.exe"), values)
        self.assertIs(options["version"], versioninfo.VSVersionInfo.return_value)

    def test_invalid_windows_version_fails_explicitly(self) -> None:
        for version in ("1.2rc1", "1.2.3.4.5", "65536.0", "-1.0"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                run_spec("win32", version)

    def test_unsupported_platform_fails_explicitly(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "macOS and Windows only"):
            run_spec("linux")
