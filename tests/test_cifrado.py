"""
Pruebas de cifrado.py (Fernet real, vía la librería `cryptography`) --
capa de cifrado simétrico usada por db_finanzas.py para los campos
sensibles de correo_config (email, app_password, cedula).

IMPORTANTE -- aislamiento de filesystem: la clave (`cifrado.key`) se
resuelve en cada llamada preguntándole a `db_finanzas.DATA_DIR` (import
diferido dentro de cifrado._cargar_fernet, ver ese módulo). Por eso acá
NO se toca `cifrado.py` directamente: basta con parchear `db.DATA_DIR`
a un `tmp_path`, igual que hace `tests/test_db_correo_config.py`. Nunca
toca data/cifrado.key real.

Este archivo NO hace "import app" (reservado a tests/test_app_integration.py).
"""
import pytest
from cryptography.fernet import InvalidToken

import cifrado
import db_finanzas as db


def _usar_data_dir(monkeypatch, tmp_path, nombre="data"):
    """Apunta db.DATA_DIR a una carpeta temporal nueva -- mismo patrón que
    la fixture `conn` de test_db_correo_config.py, pero sin crear la BD
    (estos tests no la necesitan)."""
    data_dir = tmp_path / nombre
    data_dir.mkdir()
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    return data_dir


# ----------------------------- cifrar / descifrar: básico -----------------------------

def test_cifrar_y_descifrar_devuelve_el_texto_original(monkeypatch, tmp_path):
    """Round-trip básico."""
    _usar_data_dir(monkeypatch, tmp_path)

    original = "clave-app-super-secreta"
    cifrado_valor = cifrado.cifrar(original)

    assert cifrado.descifrar(cifrado_valor) == original


def test_cifrar_none_devuelve_none_tal_cual(monkeypatch, tmp_path):
    _usar_data_dir(monkeypatch, tmp_path)
    assert cifrado.cifrar(None) is None


def test_cifrar_cadena_vacia_devuelve_cadena_vacia_tal_cual(monkeypatch, tmp_path):
    _usar_data_dir(monkeypatch, tmp_path)
    assert cifrado.cifrar("") == ""


def test_descifrar_none_devuelve_none_tal_cual(monkeypatch, tmp_path):
    _usar_data_dir(monkeypatch, tmp_path)
    assert cifrado.descifrar(None) is None


def test_descifrar_cadena_vacia_devuelve_cadena_vacia_tal_cual(monkeypatch, tmp_path):
    _usar_data_dir(monkeypatch, tmp_path)
    assert cifrado.descifrar("") == ""


def test_valor_cifrado_no_contiene_el_texto_original(monkeypatch, tmp_path):
    """Confirma que de verdad está ofuscado -- no es un no-op que
    devuelve el mismo texto disfrazado."""
    _usar_data_dir(monkeypatch, tmp_path)

    original = "correo.usuario@example.com"
    cifrado_valor = cifrado.cifrar(original)

    assert original not in cifrado_valor
    assert cifrado_valor != original


# ----------------------------- descifrar: valores inválidos -----------------------------

def test_descifrar_texto_plano_arbitrario_lanza_valueerror_no_invalidtoken(monkeypatch, tmp_path):
    """Texto que nunca fue cifrado por este módulo (ej. dato viejo de
    antes de que existiera cifrado.py) debe fallar con ValueError, NUNCA
    con la excepción nativa InvalidToken de `cryptography` -- el resto
    del código (_descifrar_fila_correo) solo atrapa ValueError."""
    _usar_data_dir(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        cifrado.descifrar("esto-es-texto-plano-comun")


def test_descifrar_string_arbitrario_no_base64_tambien_lanza_valueerror(monkeypatch, tmp_path):
    _usar_data_dir(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        cifrado.descifrar("###no-es-un-token-valido###")


def test_invalidtoken_no_se_propaga_como_tal(monkeypatch, tmp_path):
    """Refuerza explícitamente el requisito del enunciado: descifrar()
    nunca deja escapar cryptography.fernet.InvalidToken tal cual."""
    _usar_data_dir(monkeypatch, tmp_path)

    try:
        cifrado.descifrar("no-es-un-token-fernet")
    except InvalidToken:
        assert False, "descifrar() no debe propagar InvalidToken -- debe envolverla en ValueError"
    except ValueError:
        pass
    else:
        assert False, "descifrar() de un valor inválido debería haber lanzado ValueError"


# ----------------------------- esta_cifrado -----------------------------

def test_esta_cifrado_none_es_true(monkeypatch, tmp_path):
    """None/"" cuentan como "nada que migrar"."""
    _usar_data_dir(monkeypatch, tmp_path)
    assert cifrado.esta_cifrado(None) is True


def test_esta_cifrado_cadena_vacia_es_true(monkeypatch, tmp_path):
    _usar_data_dir(monkeypatch, tmp_path)
    assert cifrado.esta_cifrado("") is True


def test_esta_cifrado_de_un_valor_recien_cifrado_es_true(monkeypatch, tmp_path):
    _usar_data_dir(monkeypatch, tmp_path)
    valor = cifrado.cifrar("dato-sensible")
    assert cifrado.esta_cifrado(valor) is True


def test_esta_cifrado_de_texto_plano_comun_es_false(monkeypatch, tmp_path):
    """Caso central de la migración: un valor viejo, guardado antes de
    que existiera este módulo, debe detectarse como pendiente."""
    _usar_data_dir(monkeypatch, tmp_path)
    assert cifrado.esta_cifrado("correo-viejo@example.com") is False


# ----------------------------- claves distintas / aislamiento -----------------------------

def test_descifrar_con_otra_clave_falla_con_valueerror(monkeypatch, tmp_path):
    """Cifrado con la clave de una "instalación", intentar descifrar con
    la clave de otra -- debe fallar limpio, nunca devolver basura ni
    lanzar la excepción cruda de cryptography."""
    _usar_data_dir(monkeypatch, tmp_path, "data_a")
    valor_cifrado_con_clave_a = cifrado.cifrar("secreto-de-la-instalacion-a")

    _usar_data_dir(monkeypatch, tmp_path, "data_b")  # genera una clave.key NUEVA en data_b

    with pytest.raises(ValueError):
        cifrado.descifrar(valor_cifrado_con_clave_a)


def test_cache_de_fernet_no_contamina_entre_data_dirs_distintos(monkeypatch, tmp_path):
    """Aislamiento entre tests con tmp_path distintos: al cambiar
    db.DATA_DIR a una carpeta sin cifrado.key todavía, debe generarse una
    clave NUEVA (no reusar la cacheada del DATA_DIR anterior)."""
    data_dir_a = _usar_data_dir(monkeypatch, tmp_path, "data_a")
    cifrado.cifrar("fuerza-la-creacion-de-cifrado.key-en-a")
    clave_a = (data_dir_a / "cifrado.key").read_bytes()

    data_dir_b = _usar_data_dir(monkeypatch, tmp_path, "data_b")
    assert not (data_dir_b / "cifrado.key").exists()  # todavía no existe

    cifrado.cifrar("fuerza-la-creacion-de-cifrado.key-en-b")

    assert (data_dir_b / "cifrado.key").exists()
    clave_b = (data_dir_b / "cifrado.key").read_bytes()
    assert clave_b != clave_a


def test_clave_persiste_entre_llamadas_dentro_del_mismo_data_dir(monkeypatch, tmp_path):
    """Dentro del MISMO DATA_DIR, cifrar/descifrar varias veces seguidas
    no debe regenerar cifrado.key -- debe reusar el archivo ya creado."""
    data_dir = _usar_data_dir(monkeypatch, tmp_path)

    cifrado.cifrar("primer-uso-crea-la-clave")
    clave_path = data_dir / "cifrado.key"
    assert clave_path.exists()
    contenido_inicial = clave_path.read_bytes()

    # varias llamadas más, mismo DATA_DIR:
    valor = cifrado.cifrar("segundo-uso")
    cifrado.descifrar(valor)
    cifrado.cifrar("tercer-uso")

    assert clave_path.read_bytes() == contenido_inicial


def test_dos_valores_cifrados_con_la_misma_clave_se_descifran_bien_cada_uno(monkeypatch, tmp_path):
    """Complementa el test de contaminación: dentro del mismo DATA_DIR,
    varios valores cifrados en la misma "sesión" se descifran cada uno a
    lo suyo, sin mezclarse."""
    _usar_data_dir(monkeypatch, tmp_path)

    c1 = cifrado.cifrar("valor-uno")
    c2 = cifrado.cifrar("valor-dos")

    assert cifrado.descifrar(c1) == "valor-uno"
    assert cifrado.descifrar(c2) == "valor-dos"
