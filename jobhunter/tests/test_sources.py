import json
import unittest

from jobhunter.collectors import gupy, infojobs, jsonld, vagaja


def pagina(jp):
    return f'<html><script data-rh="true" type="application/ld+json">{json.dumps(jp)}</script></html>'


VAGAJA = {"@type": "JobPosting", "title": "Analista de Suporte Júnior", "datePosted": "2026-10-08",
          "description": "<h2>Sobre</h2><p>CLT e teletrabalho.</p><ul><li>Atender clientes</li></ul>",
          "hiringOrganization": {"name": "NETPRECISION"}, "employmentType": "FULL_TIME",
          "baseSalary": {"value": {"minValue": 2617, "unitText": "MONTH"}}, "jobLocationType": "TELECOMMUTE",
          "identifier": {"value": "BCCQZDHN8V"}}
INFOJOBS = {"@type": "JobPosting", "title": "Analista\xa0Contábil", "employmentType": "Jornada completa",
            "description": "Regime de contratação de tipo Prestador de Serviços (PJ)<br>Modelo: 100% Remoto (Home Office)",
            "datePosted": "2026-10-19T03:00:00.0000000", "validThrough": "2026-11-02T03:00:00.0000000",
            "hiringOrganization": {"name": "Empresa confidencial"}}


class JsonLd(unittest.TestCase):
    def test_vagaja(self):
        j = jsonld.normalize(jsonld.job_posting(pagina(VAGAJA)), "vagaja", "BCCQZDHN8V", "https://vaga-ja.com/vagas/x/y")
        self.assertEqual(j["id"], "vagaja:BCCQZDHN8V")
        self.assertEqual((j["workplace"], j["kind"], j["company"]), ("remote", "efetivo", "NETPRECISION"))
        self.assertTrue(j["description"].startswith("Salário: R$ 2.617,00"))
        self.assertIn("Atender clientes", j["description"])

    def test_infojobs_pj_remoto(self):
        j = jsonld.normalize(jsonld.job_posting(pagina(INFOJOBS)), "infojobs", "1", "u")
        self.assertEqual((j["workplace"], j["kind"], j["title"]), ("remote", "pj", "Analista Contábil"))
        self.assertEqual(j["deadline"], "2026-11-02T03:00:00")

    def test_pj_vence_rotulo_de_estagio(self):
        jp = dict(INFOJOBS, employmentType="", title="Assistente Administrativo",
                  description="Área Profissional: Estagiário em Administração<br>Modelo: PJ, home office, 20h/semana")
        self.assertEqual(jsonld.normalize(jp, "infojobs", "2", "u")["kind"], "pj")
        jp2 = dict(jp, title="Estágio Administrativo", description="Bolsa-auxílio, home office")
        self.assertEqual(jsonld.normalize(jp2, "infojobs", "3", "u")["kind"], "estagio")

    def test_sem_jobposting(self):
        self.assertIsNone(jsonld.job_posting('<script type="application/ld+json">{"@type":"Organization"}</script>'))
        self.assertIsNone(jsonld.job_posting('<script type="application/ld+json">{quebrado</script>'))

    def test_hibrido_nao_e_remoto(self):
        jp = dict(INFOJOBS, description="Modelo híbrido: 3 dias presencial e home office às sextas")
        self.assertEqual(jsonld.normalize(jp, "infojobs", "1", "u")["workplace"], "hybrid")


class Fontes(unittest.TestCase):
    def test_vagaja_filtra_pelo_slug_do_titulo(self):
        xml = ("<loc>https://vaga-ja.com/vagas/suporte-ltda/vendedor</loc>"
               "<loc>https://vaga-ja.com/vagas/netprecision/analista-de-suporte-junior</loc>")
        self.assertEqual(vagaja.candidatas(xml, {"suporte"}), ["https://vaga-ja.com/vagas/netprecision/analista-de-suporte-junior"])

    def test_infojobs_cards(self):
        html = ('<div id="vacancy1" data-modelversion="" data-id="12128558" class="pt-24 js_vacancyLoad js_rowCard" '
                'data-href="/vaga-de-analista__12128558.aspx" data-x="1">')
        self.assertEqual(infojobs.cards(html), [("12128558", "/vaga-de-analista__12128558.aspx")])

    def test_regras_aceitam_data_sem_fuso(self):
        from datetime import datetime, timezone
        from jobhunter import rules
        from jobhunter.run import load_cfg
        j = jsonld.normalize(jsonld.job_posting(pagina(VAGAJA)), "vagaja", "X", "u")
        j["deadline"] = "2026-11-02T03:00:00"
        d = rules.evaluate(j, load_cfg(), datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.assertNotIn("prazo", d.reason)

    def test_gupy_externa_nao_e_gupy(self):
        raw = {"id": 1000019064, "name": "Analista", "jobUrl": "https://vaga-ja.com/vagas/netprecision/x?a=1"}
        self.assertEqual(gupy.normalize(raw)["source"], "gupy-ext")
        raw = {"id": 1, "name": "Analista", "jobUrl": "https://attus.gupy.io/job/abc?x=1"}
        self.assertEqual(gupy.normalize(raw)["source"], "gupy")


if __name__ == "__main__":
    unittest.main()
