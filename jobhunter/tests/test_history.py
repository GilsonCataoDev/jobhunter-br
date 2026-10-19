"""Linhas REAIS lidas da página 'Minhas candidaturas' da Gupy em 18/10/2026."""
import unittest

from jobhunter.executor import history

REAIS = [
    {"empresa": "Rede D'Or", "vaga": "Farmacêutico (a) | Hospital Aeroporto", "progresso": "2/9", "id": "767682104"},
    {"empresa": "Alper Carreiras", "vaga": "Assistente Implantação II", "progresso": "3/8", "id": "767675323"},
    {"empresa": "SoftExpert", "vaga": "Desenvolvedor(a) Full Stack Júnior (PHP/React)", "progresso": "1/6", "id": "767580592"},
    {"empresa": "Omie", "vaga": "Estagiário(a) de Suporte Técnico (Oneflow)", "progresso": "3/7", "id": "767580585"},
    {"empresa": "Grupo TecnoSpeed 💙", "vaga": "Estagiário(a) Consultoria Técnica NFSE", "progresso": "2/5", "id": "767577647"},
    {"empresa": "", "vaga": "", "progresso": "", "id": ""},
]


class TestHistorico(unittest.TestCase):
    def test_parse(self):
        rows = history.parse_rows(REAIS)
        self.assertEqual(len(rows), 5)                       # o cartão vazio foi descartado
        self.assertEqual(rows[1]["etapa"], 3)
        self.assertEqual(rows[1]["etapas"], 8)
        self.assertEqual(rows[4]["empresa"], "Grupo TecnoSpeed")   # emoji removido

    def test_progresso_ausente_nao_quebra(self):
        r = history.parse_rows([{"empresa": "X", "vaga": "Y", "progresso": "", "id": ""}])[0]
        self.assertEqual((r["etapa"], r["etapas"]), (0, 0))

    def test_faltando_no_log(self):
        rows = history.parse_rows(REAIS)
        log = {"Alper Seguros", "Alper Carreiras", "Grupo TecnoSpeed", "Omie"}
        nomes = {r["empresa"] for r in history.faltando_no_log(rows, log)}
        self.assertEqual(nomes, {"Rede D'Or", "SoftExpert"})   # Omie (3 palavras iguais) e TecnoSpeed já estão no log


    def test_nomes_do_log_diferentes_dos_da_gupy(self):
        # erro real: log "Alper Seguros"/"Farmácias Pague Menos" x Gupy "Alper Carreiras"/"Pague Menos e Extrafarma"
        rows = history.parse_rows([
            {"empresa": "Alper Carreiras", "vaga": "Assistente", "progresso": "3/8", "id": "1"},
            {"empresa": "Pague Menos e Extrafarma", "vaga": "Farmacêutica", "progresso": "2/6", "id": "2"},
            {"empresa": "Quality Assurance Corp", "vaga": "QA", "progresso": "1/5", "id": "3"}])
        log = {"Alper Seguros", "Farmácias Pague Menos", "Quality Digital"}
        self.assertEqual([r["empresa"] for r in history.faltando_no_log(rows, log)], ["Quality Assurance Corp"])


if __name__ == "__main__":
    unittest.main()
