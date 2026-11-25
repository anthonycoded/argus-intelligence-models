"""DISPOSABLE CONTAINER ONLY. Never import this module on the host.

The controller supplies only a hash-verified artifact and fixed numeric probes.
Pickle loading is intentionally executable and confined to the isolated worker.
"""
import hashlib
import importlib.metadata
import json
from pathlib import Path


def main():
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    root = Path('/input')
    config = json.loads((root / 'config.json').read_text())
    raw = (root / 'head.joblib').read_bytes()
    if hashlib.sha256(raw).hexdigest() != config['expected_sha256']:
        raise ValueError('Source digest mismatch')
    # THE ONLY pickle deserialization in the conversion procedure.
    model = joblib.load(root / 'head.joblib')
    if (type(model) is not LogisticRegression or model.coef_.shape != (1, 384)
            or model.intercept_.shape != (1,) or model.n_features_in_ != 384
            or model.classes_.tolist() != [0, 1]
            or not np.isfinite(model.coef_).all() or not np.isfinite(model.intercept_).all()):
        raise ValueError('Unsupported fitted classifier')
    vectors = np.asarray(config['probes'], dtype=np.float64)
    print(json.dumps({'coefficients': model.coef_[0].tolist(),
        'intercept': float(model.intercept_[0]), 'classes': model.classes_.tolist(),
        'probabilities': model.predict_proba(vectors).tolist(),
        'predictions': model.predict(vectors).tolist(),
        'packages': {p: importlib.metadata.version(p) for p in config['packages']}},
        allow_nan=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
