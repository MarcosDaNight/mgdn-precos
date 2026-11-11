from datetime import datetime, timedelta, timezone

from conftest import make_config
from precos import schedule

TZ = timezone(timedelta(hours=-3))  # Recife não tem horário de verão


def cfg():
    return make_config(schedule={"collect_every_hours": 6, "summary_at": "09:00",
                                 "burst": {"from": __import__("datetime").date(2026, 11, 20),
                                           "to": __import__("datetime").date(2026, 12, 1), "every_hours": 1}})


def local(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=TZ)


def test_intervalo_normal_e_na_black_friday():
    c = cfg()
    assert schedule.collect_interval(local(2026, 11, 19, 23, 59), c) == timedelta(hours=6)
    assert schedule.collect_interval(local(2026, 11, 20, 0, 0), c) == timedelta(hours=1)
    assert schedule.collect_interval(local(2026, 11, 27, 12), c) == timedelta(hours=1)
    assert schedule.collect_interval(local(2026, 12, 1, 23, 59), c) == timedelta(hours=1)
    assert schedule.collect_interval(local(2026, 12, 2, 0, 0), c) == timedelta(hours=6)


def test_a_janela_usa_a_data_de_recife_e_nao_a_utc():
    c = cfg()
    # 2026-11-19 23:30 em Recife já é 2026-11-20 02:30 UTC: ainda NÃO é a janela
    assert schedule.collect_interval(datetime(2026, 11, 20, 2, 30, tzinfo=timezone.utc), c) == timedelta(hours=6)


def test_coleta_vence_pelo_intervalo():
    c = cfg()
    now = local(2026, 11, 10, 12)
    assert schedule.collect_due(now, None, c)
    assert not schedule.collect_due(now, now - timedelta(hours=5, minutes=59), c)
    assert schedule.collect_due(now, now - timedelta(hours=6), c)
    burst = local(2026, 11, 25, 12)
    assert not schedule.collect_due(burst, burst - timedelta(minutes=59), c)
    assert schedule.collect_due(burst, burst - timedelta(hours=1), c)


def test_resumo_so_depois_das_9h_de_recife_e_uma_vez_por_dia():
    c = cfg()
    assert not schedule.summary_due(local(2026, 11, 10, 8, 59), None, c)
    assert schedule.summary_due(local(2026, 11, 10, 9, 0), None, c)
    sent = local(2026, 11, 10, 9, 1)
    assert not schedule.summary_due(local(2026, 11, 10, 15), sent, c)
    assert not schedule.summary_due(local(2026, 11, 11, 8, 59), sent, c)
    assert schedule.summary_due(local(2026, 11, 11, 9, 0), sent, c)


def test_9h_de_recife_e_12h_utc():
    c = cfg()
    assert schedule.summary_due(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc), None, c)
    assert not schedule.summary_due(datetime(2026, 11, 10, 11, 59, tzinfo=timezone.utc), None, c)
