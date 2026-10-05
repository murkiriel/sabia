"""O que o config lê do ambiente, para o mesmo código rodar aqui, num repositório de teste e no público."""
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config  # noqa: E402

ENV_VARS = ("SABIA_REPO", "GITHUB_REPOSITORY", "SABIA_KEEP_GENERATIONS", "SABIA_NODE_STORAGE")


def reload_config(**env):
    clean = {k: v for k, v in os.environ.items() if k not in ENV_VARS}
    with mock.patch.dict(os.environ, {**clean, **env}, clear=True):
        return importlib.reload(config)


class EnvironmentTest(unittest.TestCase):
    def tearDown(self):
        reload_config()  # devolve o config ao padrão para os outros testes

    def test_default_is_public_repository(self):
        c = reload_config()
        self.assertEqual("Murkiriel/sabia", c.GITHUB_REPO)
        self.assertEqual("https://github.com/Murkiriel/sabia/releases/download/{tag}/", c.RELEASE_URL)

    def test_actions_repository(self):
        c = reload_config(GITHUB_REPOSITORY="Murkiriel/sabia-teste")
        self.assertEqual("Murkiriel/sabia-teste", c.GITHUB_REPO)
        self.assertIn("/sabia-teste/releases/download/", c.RELEASE_URL)

    def test_sabia_repo_wins_over_actions(self):
        c = reload_config(GITHUB_REPOSITORY="outro/repo", SABIA_REPO="Murkiriel/sabia")
        self.assertEqual("Murkiriel/sabia", c.GITHUB_REPO)

    def test_kept_generations(self):
        self.assertEqual(3, reload_config().KEEP_GENERATIONS)
        self.assertEqual(5, reload_config(SABIA_KEEP_GENERATIONS="5").KEEP_GENERATIONS)
        self.assertEqual(0, reload_config(SABIA_KEEP_GENERATIONS="0").KEEP_GENERATIONS)  # 0 = não apaga

    def test_node_storage(self):
        """Onde o pyosmium guarda as coordenadas dos nós: na memória por padrão; o Brasil inteiro pode pedir disco."""
        self.assertEqual("flex_mem", reload_config().NODE_STORAGE)
        self.assertEqual("sparse_file_array,/tmp/nos.bin",
                         reload_config(SABIA_NODE_STORAGE="sparse_file_array,/tmp/nos.bin").NODE_STORAGE)


class StatesTest(unittest.TestCase):
    def test_27_states_with_ibge_codes(self):
        self.assertEqual(27, len(config.STATES))
        self.assertEqual(sorted(config.STATES), sorted(config.IBGE_STATE_CODES.values()))
        self.assertEqual("GO", config.IBGE_STATE_CODES["52"])
        self.assertEqual("Distrito Federal", config.STATES["DF"])


if __name__ == "__main__":
    unittest.main()
