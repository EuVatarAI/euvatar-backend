import unittest

from app.application.services.image_prompt_builder import build_editorial_prompt


class ImagePromptBuilderTests(unittest.TestCase):
    def test_maps_mulher_castanho_to_beautiful_brunette_woman(self):
        prompt = build_editorial_prompt("mulher", "castanho")
        self.assertIn("professional color studio portrait of a beautiful brunette woman, medium shot.", prompt)

    def test_maps_homem_preto_to_handsome_black_haired_man(self):
        prompt = build_editorial_prompt("homem", "preto")
        self.assertIn("professional color studio portrait of a handsome black-haired man, medium shot.", prompt)

    def test_maps_ruivo_and_grisalho_variants(self):
        prompt_ruivo = build_editorial_prompt("mulher", "ruivo")
        prompt_grisalho = build_editorial_prompt("homem", "grisalho")
        self.assertIn("beautiful red-haired woman", prompt_ruivo)
        self.assertIn("handsome gray-haired man", prompt_grisalho)

    def test_prompt_keeps_fixed_editorial_constraints(self):
        prompt = build_editorial_prompt("mulher", "loiro")
        self.assertIn("Do not add wrinkles or signs of aging.", prompt)
        self.assertIn("Strong solid blue seamless background, infinite studio backdrop.", prompt)
        self.assertIn("Real human skin with visible pores and natural skin texture.", prompt)

    def test_invalid_gender_raises(self):
        with self.assertRaises(ValueError) as ctx:
            build_editorial_prompt("nao_definido", "castanho")
        self.assertEqual(str(ctx.exception), "invalid_gender")

    def test_invalid_hair_color_raises(self):
        with self.assertRaises(ValueError) as ctx:
            build_editorial_prompt("mulher", "rosa")
        self.assertEqual(str(ctx.exception), "invalid_hair_color")


if __name__ == "__main__":
    unittest.main()

