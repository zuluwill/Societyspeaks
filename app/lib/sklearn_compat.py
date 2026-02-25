"""
Shared scikit-learn availability layer.

Performs a single module-level import attempt for scikit-learn, including
upfront verification of native shared library dependencies (libgomp,
libopenblas/libblas).  An [Errno 5] Input/output error at import time almost
always means the dynamic linker found the .so file but could not read one of
those transitive C dependencies — not a straightforward Python import failure.

All consumers (clustering.py, consensus_engine.py, …) should import from here
rather than importing sklearn directly inside functions, so the expensive
import + native-lib check happens exactly once per process instead of on
every scheduler tick or request handler invocation.
"""
import ctypes
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Native shared library verification
# ---------------------------------------------------------------------------
# sklearn's compiled C extensions (e.g. _isotonic, _dist_metrics) dlopen
# libgomp and libblas/libopenblas at load time.  If those are missing or
# unreadable in the container the import raises OSError [Errno 5] rather than
# ImportError, which is why the catch must include OSError.
# ---------------------------------------------------------------------------

def _try_load_native_lib(candidates: list) -> tuple:
    """
    Attempt to load any library from the candidates list via ctypes.
    Returns (success: bool, loaded_name: str | None, last_error: OSError | None).
    """
    last_err = None
    for name in candidates:
        try:
            ctypes.CDLL(name)
            return True, name, None
        except OSError as exc:
            last_err = exc
    return False, None, last_err


_NATIVE_LIBS_OK = True

_NATIVE_LIB_GROUPS = [
    # OpenMP runtime — required by sklearn's parallel Cython extensions
    ["libgomp.so.1", "libgomp.so"],
    # BLAS/OpenBLAS — required for linear algebra in sklearn/numpy C extensions
    ["libopenblas.so.0", "libopenblas.so", "libblas.so.3", "libblas.so"],
]

for _candidates in _NATIVE_LIB_GROUPS:
    _ok, _loaded, _err = _try_load_native_lib(_candidates)
    if _ok:
        logger.debug("Native library verified: %s", _loaded)
    else:
        logger.warning(
            "Native library not loadable (%s): %s — sklearn C extensions may "
            "fail with [Errno 5] Input/output error at import or call time.",
            _candidates[0],
            _err,
        )
        _NATIVE_LIBS_OK = False


# ---------------------------------------------------------------------------
# 2. Module-level sklearn import (runs once per process)
# ---------------------------------------------------------------------------

SKLEARN_AVAILABLE: bool = False

cosine_similarity = None
AgglomerativeClustering = None
KMeans = None
PCA = None
silhouette_score = None

try:
    from sklearn.metrics.pairwise import cosine_similarity as _cosine_similarity
    from sklearn.cluster import AgglomerativeClustering as _AgglomerativeClustering
    from sklearn.cluster import KMeans as _KMeans
    from sklearn.decomposition import PCA as _PCA
    from sklearn.metrics import silhouette_score as _silhouette_score

    cosine_similarity = _cosine_similarity
    AgglomerativeClustering = _AgglomerativeClustering
    KMeans = _KMeans
    PCA = _PCA
    silhouette_score = _silhouette_score

    SKLEARN_AVAILABLE = True
    logger.info("scikit-learn imported successfully.")

except (OSError, ImportError) as _sklearn_err:
    logger.warning(
        "scikit-learn unavailable at import time (%s: %s). "
        "All clustering and PCA operations will use numpy fallback implementations.",
        type(_sklearn_err).__name__,
        _sklearn_err,
    )


# ---------------------------------------------------------------------------
# 3. Startup health-check helper
# ---------------------------------------------------------------------------

def check_sklearn_health() -> dict:
    """
    Return a summary dict of sklearn and native-library availability.
    Intended to be called once from create_app() so issues surface immediately
    at startup rather than silently at the first scheduler tick.
    """
    return {
        "sklearn_available": SKLEARN_AVAILABLE,
        "native_libs_ok": _NATIVE_LIBS_OK,
    }
