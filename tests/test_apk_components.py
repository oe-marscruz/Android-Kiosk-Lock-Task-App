import importlib.util
import pathlib
import unittest

path = pathlib.Path(__file__).resolve().parents[1] / "tools" / "check_apk_components.py"
spec = importlib.util.spec_from_file_location("apk_components", path)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ComponentTests(unittest.TestCase):
    def test_android_component_name_resolution(self):
        self.assertEqual(checker.resolve_name("a.b", ".Home"), "a.b.Home")
        self.assertEqual(checker.resolve_name("a.b", "Home"), "a.b.Home")
        self.assertEqual(checker.resolve_name("a.b", "x.y.Home"), "x.y.Home")

    def test_manifest_uses_component_attribute_not_nested_intent(self):
        xml = '''  E: manifest
    A: package="a.b"
      E: application
          E: activity
            A: android:name(0x1)=".Home"
              E: intent-filter
                  E: category
                    A: android:name(0x1)="android.intent.category.HOME"
          E: receiver
            A: android:name(0x1)="Admin"
'''
        components = checker.manifest_components(xml)
        self.assertEqual([(c["name"], c["home"]) for c in components],
                         [("a.b.Home", True), ("a.b.Admin", False)])

    def test_invalid_dex_rejected(self):
        with self.assertRaises(ValueError):
            checker.dex_classes(b"not a dex")


if __name__ == "__main__":
    unittest.main()