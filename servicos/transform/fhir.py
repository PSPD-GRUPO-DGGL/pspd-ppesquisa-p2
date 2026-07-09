"""Montagem de Resources e Bundles HL7/FHIR R4.

Recebe dados já projetados pelo nível de acesso. Ver docs/mapeamento-fhir.md
para o mapeamento e para as decisões de conformidade (ausência de
`coding.system` e de UCUM, campos obrigatórios fixados).
"""

from __future__ import annotations

from datetime import datetime, timezone

from anonimizacao import AGGREGATED, ANONYMIZED, FULL, PARTIAL

SYSTEM_CPF = "urn:oid:2.16.76.1.3.1"
SYSTEM_CNS = "https://fhir.saude.gov.br/sid/cns"

EXT_FAIXA_ETARIA = "http://hl7.org/fhir/StructureDefinition/patient-ageRange"
EXT_ESTATISTICAS = "urn:pspd:estatisticas-exames"

# tipo_atendimento -> HL7 v3 ActEncounterCode
_CLASSE_ENCONTRO = {
    "Ambulatorial": ("AMB", "ambulatory"),
    "Retorno": ("AMB", "ambulatory"),
    "Emergencia": ("EMER", "emergency"),
    "Internacao": ("IMP", "inpatient encounter"),
}


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def montar_patient(p: dict, nivel: int) -> dict:
    if nivel == AGGREGATED:
        raise ValueError("AGGREGATED não emite Patient")

    recurso: dict = {"resourceType": "Patient", "id": p["id"], "gender": p["genero"]}

    if nivel == ANONYMIZED:
        recurso["address"] = [{"state": p["estado"]}]
        recurso["extension"] = [
            {"url": EXT_FAIXA_ETARIA, "valueString": p["faixa_etaria"]}
        ]
        return recurso

    recurso["name"] = [{"text": p["nome"]}]
    recurso["birthDate"] = p["data_nascimento"]
    recurso["address"] = [{"city": p["cidade"], "state": p["estado"]}]

    if nivel == FULL:
        recurso["identifier"] = [
            {"system": SYSTEM_CPF, "value": p["cpf"]},
            {"system": SYSTEM_CNS, "value": p["cns"]},
        ]
    return recurso


def montar_encounter(a: dict, ref_paciente: str) -> dict:
    codigo, display = _CLASSE_ENCONTRO.get(a["tipo_atendimento"], ("AMB", "ambulatory"))
    recurso = {
        "resourceType": "Encounter",
        "id": a["id_atendimento"],
        "status": "finished",
        "class": {"code": codigo, "display": display},
        "subject": {"reference": f"Patient/{ref_paciente}"},
        "period": {"start": a["data_inicio"]},
        "serviceType": {"text": a["setor"]},
    }
    if a.get("data_fim"):
        recurso["period"]["end"] = a["data_fim"]
    return recurso


def montar_condition(e: dict, ref_paciente: str) -> dict:
    recurso = {
        "resourceType": "Condition",
        "id": str(e["id_evento"]),
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"code": e["codigo_tipo_evento"]}], "text": e["descricao"]},
        "subject": {"reference": f"Patient/{ref_paciente}"},
        "onsetDateTime": e["data_evento"],
    }
    if e.get("id_atendimento"):
        recurso["encounter"] = {"reference": f"Encounter/{e['id_atendimento']}"}
    return recurso


def montar_observation(e: dict, ref_paciente: str) -> dict:
    recurso = {
        "resourceType": "Observation",
        "id": str(e["id_evento"]),
        "status": "final",
        "code": {"coding": [{"code": e["codigo_tipo_evento"]}], "text": e["descricao"]},
        "subject": {"reference": f"Patient/{ref_paciente}"},
        "effectiveDateTime": e["data_evento"],
        "valueQuantity": {"value": e["valor"], "unit": e["unidade"]},
    }
    if e.get("id_atendimento"):
        recurso["encounter"] = {"reference": f"Encounter/{e['id_atendimento']}"}
    return recurso


def montar_medication_request(e: dict, ref_paciente: str) -> dict:
    # status e intent são obrigatórios em R4 e não existem no banco.
    return {
        "resourceType": "MedicationRequest",
        "id": str(e["id_evento"]),
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [{"code": e["codigo_tipo_evento"]}],
            "text": e["descricao"],
        },
        "subject": {"reference": f"Patient/{ref_paciente}"},
        "authoredOn": e["data_evento"],
        "dosageInstruction": [
            {"doseAndRate": [{"doseQuantity": {"value": e["valor"], "unit": e["unidade"]}}]}
        ],
    }


_POR_TIPO_EVENTO = {
    "Condicao": montar_condition,
    "Observacao": montar_observation,
    "Medicacao": montar_medication_request,
}


def montar_bundle(
    pacientes_projetados: list[dict],
    atendimentos: list[dict],
    eventos: list[dict],
    nivel: int,
    ids_exibidos: dict[str, str],
) -> tuple[dict, dict[str, int]]:
    """Devolve (bundle, contagem por resourceType).

    `ids_exibidos` traduz o id real para o exibido nas referências. Linhas de
    paciente ausente do mapa são descartadas.
    """
    entradas = []
    contagem: dict[str, int] = {}

    def adicionar(recurso: dict) -> None:
        entradas.append({"resource": recurso})
        contagem[recurso["resourceType"]] = contagem.get(recurso["resourceType"], 0) + 1

    for p in pacientes_projetados:
        adicionar(montar_patient(p, nivel))

    for a in atendimentos:
        ref = ids_exibidos.get(a["id_paciente"])
        if ref is None:
            continue
        adicionar(montar_encounter(a, ref))

    for e in eventos:
        ref = ids_exibidos.get(e["id_paciente"])
        if ref is None:
            continue
        construtor = _POR_TIPO_EVENTO.get(e["tipo_evento"])
        if construtor is None:
            continue
        adicionar(construtor(e, ref))

    bundle = {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": _agora(),
        "entry": entradas,
    }
    return bundle, contagem


def montar_measure_report(agregado: dict) -> tuple[dict, dict[str, int]]:
    """MeasureReport `summary`. Não emite Patient nem identificador.

    Médias e medianas vão em extensão: `stratifier` só modela contagens.
    """

    def estratificador(rotulo: str, contagens: list[dict]) -> dict:
        return {
            "code": [{"text": rotulo}],
            "stratum": [
                {
                    "value": {"text": c["chave"]},
                    "population": [{"count": c["valor"]}],
                    "extension": [
                        {"url": "urn:pspd:percentual", "valueDecimal": c["percentual"]}
                    ],
                }
                for c in contagens
            ],
        }

    estratos = []
    for rotulo, chave in (
        ("genero", "distribuicao_sexo"),
        ("faixa-etaria", "distribuicao_faixa_etaria"),
        ("setor", "distribuicao_setor"),
        ("medicamentos", "frequencia_medicamentos"),
    ):
        if agregado.get(chave):
            estratos.append(estratificador(rotulo, agregado[chave]))

    extensoes = [
        {
            "url": EXT_ESTATISTICAS,
            "extension": [
                {"url": "codigo", "valueString": s["nome"]},
                {"url": "media", "valueDecimal": s["media"]},
                {"url": "mediana", "valueDecimal": s["mediana"]},
                {"url": "desvioPadrao", "valueDecimal": s["desvio_padrao"]},
                {"url": "n", "valueInteger": s["n"]},
                {"url": "unidade", "valueString": s.get("unidade", "")},
            ],
        }
        for s in agregado.get("estatisticas_exames", [])
    ]

    relatorio = {
        "resourceType": "MeasureReport",
        "status": "complete",
        "type": "summary",
        "measure": f"Coorte/{agregado['codigo_condicao']}",
        "date": _agora(),
        "group": [
            {
                "population": [
                    {
                        "code": {"text": "total-pacientes"},
                        "count": agregado["total_pacientes"],
                    }
                ],
                "stratifier": estratos,
            }
        ],
    }
    if extensoes:
        relatorio["extension"] = extensoes

    return relatorio, {"MeasureReport": 1}
