"""
cifrado.py
============
Cifrado simétrico (Fernet, de la librería `cryptography` -- estándar,
gratuita y de código abierto) para los campos verdaderamente sensibles
que la app necesita en texto reversible (no se pueden hashear como una
contraseña de login, porque hace falta el valor real para usarlo: la
contraseña de aplicación de Gmail para IMAP, la cédula para abrir PDFs).

Antes de esto, esos campos vivían en texto plano en data/finanzas.db --
protegidos solo porque ese archivo nunca sale de la PC y nunca se sube a
git. Eso deja de ser suficiente si el objetivo es tratar estos datos
como corresponde a información sensible (cédulas, contraseñas, correos):
ahora quedan cifrados EN LA BASE DE DATOS, con una clave que vive en un
archivo aparte (data/cifrado.key, fuera de git) -- alguien que solo
consiga finanzas.db (una copia de respaldo, por ejemplo) no puede leer
esos campos sin también tener esa clave.

⚠️ IMPORTANTE -- data/cifrado.key es la clave maestra de estos campos.
Si se pierde o se borra, ya no se puede descifrar nada de lo que ya
estaba guardado (habría que volver a cargar correo/contraseña/cédula de
cada usuario desde cero) -- igual de importante para respaldar que
data/finanzas.db. Nunca se sube a git (data/ está completo en
.gitignore).

Uso:
    from cifrado import cifrar, descifrar
    valor_cifrado = cifrar("texto sensible")       # -> str (o None si el input es None/"")
    valor_original = descifrar(valor_cifrado)      # -> str (o None si el input es None/"")
"""
from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None
_fernet_clave_path = None  # ruta con la que se cargó _fernet -- ver _cargar_fernet()


def _cargar_fernet() -> Fernet:
    """Carga la clave desde disco, generándola una sola vez si no existe
    todavía (mismo patrón que secret_key.txt en app.py).

    La ruta se pregunta a db_finanzas.DATA_DIR en cada llamada (import
    diferido acá adentro -- no arriba del archivo -- porque db_finanzas
    ya importa este módulo, y un import circular arriba rompería). Esto
    es a propósito: así, cuando los tests aíslan db.DATA_DIR a una
    carpeta temporal (patrón ya usado en toda la suite), este módulo lo
    respeta solo, sin tener que acordarse de parchear un tercer módulo
    más -- y nunca toca el data/cifrado.key real del proyecto desde un
    test. Si la ruta cambió respecto de la última llamada (nueva
    carpeta temporal en cada test), se recarga -- si no, se reusa la
    instancia ya cacheada."""
    global _fernet, _fernet_clave_path
    import db_finanzas as db

    clave_path = db.DATA_DIR / "cifrado.key"
    if _fernet is not None and _fernet_clave_path == clave_path:
        return _fernet

    clave_path.parent.mkdir(exist_ok=True)
    if not clave_path.exists():
        clave_path.write_bytes(Fernet.generate_key())
    _fernet = Fernet(clave_path.read_bytes())
    _fernet_clave_path = clave_path
    return _fernet


def cifrar(texto: str | None) -> str | None:
    """None o '' se devuelven tal cual (un campo opcional vacío no
    necesita "cifrarse" a nada) -- así el resto del código no tiene que
    acordarse de chequear None antes de llamar a esta función."""
    if not texto:
        return texto
    return _cargar_fernet().encrypt(texto.encode("utf-8")).decode("ascii")


def descifrar(texto: str | None) -> str | None:
    """Inversa de cifrar(). Lanza ValueError (no la excepción críptica
    de cryptography) si el valor no es un token Fernet válido para esta
    clave -- ej. la clave cambió, el dato está corrupto, o (ver
    esta_cifrado) todavía es texto plano de antes de esta migración."""
    if not texto:
        return texto
    try:
        return _cargar_fernet().decrypt(texto.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as e:
        raise ValueError(f"No se pudo descifrar el valor (¿clave incorrecta o dato corrupto?): {e}") from e


def esta_cifrado(texto: str | None) -> bool:
    """True si `texto` ya es un token Fernet válido para la clave
    actual. Se usa en la migración (ver db_finanzas.py) para distinguir
    filas viejas en texto plano (guardadas antes de que existiera este
    módulo) de filas ya cifradas -- sin esto, cifrar dos veces el mismo
    valor lo dejaría ilegible."""
    if not texto:
        return True  # nada que cifrar tampoco es "texto plano pendiente"
    try:
        descifrar(texto)
        return True
    except ValueError:
        return False
