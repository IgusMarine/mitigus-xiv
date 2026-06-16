import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mitigus import i18n


class I18nTest(unittest.TestCase):
    def tearDown(self):
        i18n.set_lang("en")  # não vaza idioma pra outros testes

    def test_normalize(self):
        self.assertEqual(i18n.normalize("pt"), "pt")
        self.assertEqual(i18n.normalize("es"), "es")
        self.assertEqual(i18n.normalize("banana"), "en")  # desconhecido -> en
        self.assertEqual(i18n.normalize(None), "en")

    def test_set_get(self):
        self.assertEqual(i18n.set_lang("pt"), "pt")
        self.assertEqual(i18n.get_lang(), "pt")
        self.assertEqual(i18n.set_lang("xx"), "en")  # inválido -> en

    def test_translates_per_language(self):
        i18n.set_lang("pt")
        self.assertEqual(i18n.t("tray.quit"), "Sair")
        i18n.set_lang("es")
        self.assertEqual(i18n.t("tray.quit"), "Salir")
        i18n.set_lang("en")
        self.assertEqual(i18n.t("tray.quit"), "Quit")

    def test_fallback_to_english_then_key(self):
        i18n.set_lang("pt")
        # chave inexistente -> devolve a própria chave (não quebra)
        self.assertEqual(i18n.t("nao.existe"), "nao.existe")

    def test_format_kwargs(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.t("log.margin", ms=75), "safety margin = 75ms")
        i18n.set_lang("pt")
        self.assertEqual(i18n.t("log.margin", ms=90), "margem de segurança = 90ms")
        # placeholder faltando não estoura
        self.assertIn("{ms}", i18n.t("log.margin"))

    def test_all_languages_have_the_same_keys(self):
        keys_en = set(i18n.MESSAGES["en"])
        for lang in ("pt", "es"):
            self.assertEqual(set(i18n.MESSAGES[lang]), keys_en,
                             f"chaves de '{lang}' divergem do inglês")

    def test_save_load_roundtrip(self):
        old = os.environ.get("LOCALAPPDATA")
        with tempfile.TemporaryDirectory() as d:
            os.environ["LOCALAPPDATA"] = d
            try:
                i18n.save_lang("es")
                self.assertEqual(i18n.get_lang(), "es")
                i18n.set_lang("en")            # muda só em memória
                self.assertEqual(i18n.load_lang(), "es")  # relê do disco
            finally:
                if old is None:
                    os.environ.pop("LOCALAPPDATA", None)
                else:
                    os.environ["LOCALAPPDATA"] = old


if __name__ == "__main__":
    unittest.main()
