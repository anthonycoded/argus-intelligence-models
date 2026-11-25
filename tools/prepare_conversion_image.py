"""Download hash-verified public wheels; build an offline, artifact-free image.

No pickle/model input is accepted by this preparation tool. No secrets or host
packages enter the build context. The resulting image is not a service image.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = 'python@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df'
PACKAGES = {'numpy': '2.5.5', 'scipy': '1.18.1', 'scikit-learn': '1.9.1',
    'joblib': '1.6.0', 'threadpoolctl': '3.8.0', 'narwhals': '2.29.0', 'cloudpickle': '3.1.3'}


def main():
    directory = ROOT / 'data/inference' / ('conversion-build-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    wheels = directory / 'wheels'; wheels.mkdir()
    provenance = {}
    # Public dependencies only. Deserialization occurs later, without networking.
    for package, version in PACKAGES.items():
        url = f'https://pypi.org/pypi/{package}/{version}/json'
        with urllib.request.urlopen(url, timeout=30) as response:
            metadata = json.load(response)
        candidates = [x for x in metadata['urls'] if x['packagetype'] == 'bdist_wheel'
            and (x['filename'].endswith('py3-none-any.whl') or
                 ('-cp312-cp312-manylinux' in x['filename'] and 'x86_64' in x['filename']))]
        if len(candidates) != 1: raise ValueError(f'Unambiguous Linux wheel required: {package}')
        entry = candidates[0]
        if not entry['url'].startswith('https://files.pythonhosted.org/'): raise ValueError('Non-PyPI wheel')
        with urllib.request.urlopen(entry['url'], timeout=60) as response:
            raw = response.read(100 * 1024 * 1024 + 1)
        if len(raw) > 100 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != entry['digests']['sha256']:
            raise ValueError('Public wheel checksum mismatch')
        (wheels / entry['filename']).write_bytes(raw)
        provenance[package] = {'version': version, 'filename': entry['filename'],
            'sha256': entry['digests']['sha256'], 'metadata_url': url, 'wheel_url': entry['url']}
    (directory / 'requirements.txt').write_text(''.join(
        f'{p}=={v} --hash=sha256:{provenance[p]["sha256"]}\n' for p,v in PACKAGES.items()))
    (directory / 'Dockerfile').write_text(f'FROM {BASE}\nCOPY wheels /wheels\nCOPY requirements.txt /requirements.txt\n'
        'RUN python -m pip --isolated install --no-index --require-hashes --only-binary=:all: --no-cache-dir '
        '--find-links=/wheels -r /requirements.txt\nUSER 65534:65534\n')
    tag = 'aic-head-converter:' + uuid.uuid4().hex
    subprocess.run(['docker','build','--network','none','--pull=false','--tag',tag,str(directory)], check=True)
    image = subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',tag], text=True).strip()
    record = {'base': BASE, 'image': image, 'tag': tag, 'wheels': provenance,
        'dockerfile_sha256': hashlib.sha256((directory/'Dockerfile').read_bytes()).hexdigest()}
    (directory/'build-evidence.json').write_text(json.dumps(record, indent=2))
    print(json.dumps({'build_evidence': str(directory/'build-evidence.json'), 'image': image}))


if __name__ == '__main__': main()
