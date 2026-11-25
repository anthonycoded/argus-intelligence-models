"""One-time authorized conversion; host NEVER imports joblib/sklearn/pickle.

Run only after inspecting the public-dependency build evidence. Docker is a
kernel isolation boundary, not protection against a container/runtime escape.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.global_io import encoded, read_object, publish_directory, now
from src.inference_runtime import file_hash, encoder_identity

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = '3ff5a564931b6db164f4fa64810d30ba6d632f46942410d425f30c0037fd6bb5'
TOLERANCE = 1e-10


def probes():
    # Fixed, reproducible, no dataset inputs; zero, basis +/- and dense vectors.
    rows = [[0.] * 384]
    for i in (0, 1, 191, 383):
        for sign in (-1., 1.):
            row = [0.] * 384; row[i] = sign; rows.append(row)
    rows += [[1 / math.sqrt(384)] * 384,
             [(-1 if i % 2 else 1) / math.sqrt(384) for i in range(384)]]
    for seed in range(8):
        row = [math.sin((i+1)*(seed+1)*.137) for i in range(384)]
        norm = math.sqrt(sum(x*x for x in row)); rows.append([x/norm for x in row])
    return rows


def validate_projection(result, vectors):
    if set(result) != {'coefficients','intercept','classes','probabilities','predictions','packages'}:
        raise ValueError('Unexpected worker output')
    weights = result['coefficients']; bias = result['intercept']
    numeric = lambda x: type(x) in (int,float) and math.isfinite(x) and abs(x) <= 1e6
    if (not isinstance(weights,list) or len(weights)!=384 or not all(map(numeric,weights))
            or not numeric(bias) or result['classes'] != [0,1]
            or any(type(x) is not int for x in result['classes'])): raise ValueError('Invalid numeric head')
    if len(result['probabilities']) != len(vectors) or len(result['predictions']) != len(vectors):
        raise ValueError('Missing parity probes')
    maximum = 0.; ties = 0
    for row, original, prediction in zip(vectors,result['probabilities'],result['predictions']):
        score = math.fsum(x*y for x,y in zip(row,weights)) + bias
        p = 1/(1+math.exp(-score)) if score >= 0 else math.exp(score)/(1+math.exp(score))
        if not isinstance(original,list) or len(original)!=2 or not all(numeric(x) and 0<=x<=1 for x in original):
            raise ValueError('Invalid original probabilities')
        maximum = max(maximum, abs(original[0]-(1-p)), abs(original[1]-p))
        if type(prediction) is not int or prediction != int(score > 0): raise ValueError('Prediction parity failed')
        ties += int(score == 0)
    if maximum > TOLERANCE or ties: raise ValueError('Probability parity failed or threshold tie requires review')
    return {'probe_count':len(vectors),'probes_sha256':hashlib.sha256(encoded(vectors)).hexdigest(),
        'maximum_absolute_probability_error':maximum,'absolute_tolerance':TOLERANCE,
        'predictions_equal':True,'threshold_ties':ties,'scope':'fixed synthetic feature vectors, not accuracy'}


def bounded_worker(container):
    proc = subprocess.Popen(['docker','start','--attach',container],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    streams = [bytearray(),bytearray()]; overflow = threading.Event()
    def drain(stream, destination):
        while True:
            block=stream.read(2048)
            if not block: break
            if len(destination)+len(block)>65536: overflow.set(); break
            destination.extend(block)
    threads=[threading.Thread(target=drain,args=(s,d),daemon=True) for s,d in zip((proc.stdout,proc.stderr),streams)]
    for t in threads:t.start()
    end=time.monotonic()+60
    try:
        while proc.poll() is None:
            if overflow.is_set() or time.monotonic()>end:raise ValueError('Worker output/time limit exceeded')
            time.sleep(.05)
        for t in threads:t.join(2)
        if overflow.is_set() or proc.returncode:raise ValueError('Isolated conversion failed; no artifact published')
        from src.global_io import parse_json
        return parse_json(streams[0].decode('utf-8'))
    finally:
        if proc.poll() is None:proc.kill();proc.wait(timeout=5)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-evidence',type=Path,required=True)
    p.add_argument('--encoder',type=Path,required=True);p.add_argument('--revision',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--confirm-authorized-isolated-conversion',action='store_true')
    args=p.parse_args()
    if not args.confirm_authorized_isolated_conversion:raise ValueError('Explicit operator authorization required')
    if args.output.exists():raise FileExistsError('Frozen output exists')
    source=ROOT/'experiments/models/defense_head.joblib'
    if file_hash(source)!=EXPECTED:raise ValueError('Expected local training output digest mismatch')
    training=ROOT/'experiments/defense_classifier.py'
    if 'MODEL_DIR / "defense_head.joblib"' not in training.read_text():raise ValueError('Training output path not established')
    identity=encoder_identity(args.encoder,args.revision)
    build=read_object(args.build_evidence)
    image=build['image']
    if not isinstance(image,str) or len(image)!=71 or not image.startswith('sha256:'):raise ValueError('Pinned image ID required')
    vectors=probes()
    stage=ROOT/'data/inference'/('conversion-input-'+uuid.uuid4().hex);stage.mkdir(parents=True)
    (stage/'head.joblib').write_bytes(source.read_bytes())
    (stage/'convert.py').write_bytes((ROOT/'tools/head_conversion_payload.py').read_bytes())
    (stage/'config.json').write_bytes(encoded({'expected_sha256':EXPECTED,'probes':vectors,'packages':list(build['wheels'])}))
    if file_hash(stage/'head.joblib')!=EXPECTED:raise ValueError('Staged source mismatch')
    create=['docker','create','--network','none','--read-only','--user','65534:65534',
        '--cap-drop','ALL','--security-opt','no-new-privileges:true','--pids-limit','32',
        '--memory','512m','--memory-swap','512m','--cpus','1','--log-driver','none',
        '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=64m','--mount',f'type=bind,source={stage},target=/input,readonly',
        '--env','OPENBLAS_NUM_THREADS=1','--env','OMP_NUM_THREADS=1','--env','MKL_NUM_THREADS=1',
        '--env','HOME=/tmp','--entrypoint','python',image,'-I','-B','/input/convert.py']
    container=subprocess.check_output(create,text=True).strip()
    if len(container)!=64 or any(c not in '0123456789abcdef' for c in container):raise ValueError('Unexpected owned container identity')
    try:
        inspection=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]
        host=inspection['HostConfig'];mounts=inspection['Mounts'];config=inspection['Config']
        if (host['NetworkMode']!='none' or not host['ReadonlyRootfs'] or host['Privileged']
            or config['User']!='65534:65534' or len(mounts)!=1 or mounts[0]['Destination']!='/input'
            or mounts[0]['RW'] or host['Memory']!=512*1024*1024 or host['PidsLimit']!=32
            or host['CapDrop']!=['ALL'] or 'no-new-privileges:true' not in host['SecurityOpt']):
            raise ValueError('Isolation verification failed')
        allowed_env={'PATH','LANG','GPG_KEY','PYTHON_VERSION','PYTHON_SHA256','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','HOME'}
        if any(x.split('=',1)[0] not in allowed_env for x in config['Env']):raise ValueError('Unexpected image environment')
        result=bounded_worker(container)
        status=json.loads(subprocess.check_output(['docker','inspect',container],text=True))[0]['State']
        if status['Running'] or status['ExitCode']!=0:raise ValueError('Worker did not terminate cleanly')
    finally:
        # Only the exact ID created by this invocation is ever removed.
        subprocess.run(['docker','rm','--force',container],check=True,stdout=subprocess.DEVNULL)
    parity=validate_projection(result,vectors)
    for package,evidence in build['wheels'].items():
        if result['packages'].get(package)!=evidence['version']:raise ValueError('Worker package mismatch')
    if file_hash(source)!=EXPECTED:raise ValueError('Original source changed')
    document={'schema_version':'aic-numeric-defense-v1','encoder':identity,
        'coefficients':result['coefficients'],'intercept':result['intercept'],'classes':[0,1],
        'threshold':.5,'training_origin':'synthetic_v2','source_artifact_sha256':EXPECTED,
        'packages':result['packages'],'dataset_sha256':file_hash(ROOT/'aic1_synthetic_v2/aic1_synthetic_v2.jsonl'),
        'split_sha256':file_hash(ROOT/'aic1_synthetic_v2/group_splits.jsonl')}
    raw=encoded(document)
    manifest={'schema_version':'aic-head-conversion-trust-v1','at':now(),'model_identity':'MiniLM384 + binary logistic regression',
        'authorization':'Operator-attested local training output; one-time isolated conversion only',
        'source_relative_path':'experiments/models/defense_head.joblib','source_sha256':EXPECTED,
        'training_script_sha256':file_hash(training),'output_sha256':hashlib.sha256(raw).hexdigest(),
        'encoder':identity,'build':build,'parity':parity,'source_unchanged':True,
        'controller_sha256':file_hash(Path(__file__)),'worker_sha256':file_hash(stage/'convert.py'),
        'isolation':{'network':'none','user':config['User'],'read_only_root':True,'input_mount_read_only':True,
            'input_files':['head.joblib','convert.py','config.json'],'host_secrets_or_production_mounts':False,
            'capabilities_dropped':['ALL'],'no_new_privileges':True,'memory_bytes':host['Memory'],
            'pids':32,'cpus':1,'wall_deadline_seconds':60,'stdout_stderr_limit_each_bytes':65536,'container_removed':True},
        'limitations':['Docker shares its Linux kernel; no claim against runtime/kernel exploits',
            'Original training did not pin encoder or record dataset lineage; current hashes are observations, not proof of historical training inputs',
            'Fixed-vector parity is not accuracy, calibration, rights clearance or deployment approval']}
    publish_directory(args.output,{'head.json':raw,'trust-manifest.json':encoded(manifest)})
    print(json.dumps({'head_sha256':manifest['output_sha256'],'parity':parity,'output':str(args.output)}))


if __name__=='__main__':main()
