"""
Configuración compartida de pytest: agrega src/ al path para que los
tests puedan hacer "import db_finanzas", "import app", etc. sin
instalar el proyecto como paquete.
"""
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))
