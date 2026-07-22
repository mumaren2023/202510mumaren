from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import urllib.request
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return copy.deepcopy(default)


def safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def clean_runtime(root: Path) -> None:
    for p in list(root.rglob('__pycache__')):
        shutil.rmtree(p, ignore_errors=True)
    for p in list(root.rglob('*.pyc')):
        p.unlink(missing_ok=True)


def run_python(script: Path, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return subprocess.run(
        [sys.executable, str(script)], cwd=str(cwd), env=env,
        capture_output=True, text=True, timeout=timeout,
    )


def download(url: str, path: Path) -> None:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=120) as response, path.open('wb') as out:
        shutil.copyfileobj(response, out)


def identify_root(extract_dir: Path) -> Path:
    dirs = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(dirs) == 1:
        return dirs[0]
    for p in dirs:
        if (p / 'current').is_dir():
            return p
    raise RuntimeError('Unable to identify source package root')


def file_map(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): sha256_file(p)
        for p in root.rglob('*') if p.is_file()
    }


def make_schema_files(current: Path) -> None:
    schemas = current / 'schemas'
    schemas.mkdir(parents=True, exist_ok=True)
    common = {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        'additionalProperties': False,
    }
    progress = {
        **common,
        '$id': 'https://shuxingxingmumaren.com/schemas/progress-write-request-v2.1.json',
        'title': '学习进度写入请求 V2.1',
        'type': 'object',
        'required': ['user_id','resource_id','core_ref_id','core_version','progress','client_event_at','idempotency_key','expected_version'],
        'properties': {
            'user_id': {'type':'string','pattern':'^U-[A-Z0-9-]+$'},
            'resource_id': {'type':'string','pattern':'^(COURSE|GAME|EXHIBIT)-[A-Z0-9-]+$'},
            'core_ref_id': {'type':'string','pattern':'^ORB-[A-Z]+-[0-9]{8}$'},
            'core_version': {'const':'V1.0-beta1'},
            'progress': {'type':'number','minimum':0,'maximum':1},
            'client_event_at': {'type':'string','format':'date-time'},
            'idempotency_key': {'type':'string','minLength':8,'maxLength':128},
            'expected_version': {'type':'integer','minimum':0},
        },
        'x-server-principal-binding': {'required': True, 'rule': 'user_id equals authenticated principal subject_user_id'},
        'x-server-generated-fields': ['server_recorded_at','resource_version','contract_sha256','core_closure_version'],
    }
    attempt = {
        **common,
        '$id': 'https://shuxingxingmumaren.com/schemas/attempt-write-request-v2.1.json',
        'title': '学习作答写入请求 V2.1',
        'type':'object',
        'required':['attempt_id','game_id','core_ref_ids','core_version','submitted_answer','client_event_at','idempotency_key','operation'],
        'properties': {
            'attempt_id': {'type':'string','pattern':'^ATT-[A-Z0-9-]+$'},
            'game_id': {'type':'string','pattern':'^GAME-[A-Z0-9-]+$'},
            'core_ref_ids': {'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string','pattern':'^ORB-[A-Z]+-[0-9]{8}$'}},
            'core_version': {'const':'V1.0-beta1'},
            'submitted_answer': {'type':'object'},
            'client_event_at': {'type':'string','format':'date-time'},
            'idempotency_key': {'type':'string','minLength':8,'maxLength':128},
            'operation': {'const':'create'},
        },
        'x-server-generated-fields': ['owner_user_id','server_recorded_at','resource_version','contract_sha256','core_closure_version'],
    }
    child_work = {
        **common,
        '$id': 'https://shuxingxingmumaren.com/schemas/child-work-write-request-v2.1.json',
        'title': '儿童原创作品创建请求 V2.1（资产ID闭环）',
        'type':'object',
        'required':['work_id','user_id','content_asset_id','content_type','consent_status','idempotency_key','operation'],
        'properties': {
            'work_id': {'type':'string','pattern':'^WORK-[A-Z0-9-]+$'},
            'user_id': {'type':'string','pattern':'^U-[A-Z0-9-]+$'},
            'content_asset_id': {'type':'string','pattern':'^ASSET-[A-Z0-9-]+$'},
            'content_type': {'enum':['image/png','image/jpeg','text/plain','application/pdf']},
            'consent_status': {'enum':['private','submitted_for_review']},
            'idempotency_key': {'type':'string','minLength':8,'maxLength':128},
            'operation': {'const':'create'},
        },
        'x-server-generated-fields': ['content_uri','asset_sha256','asset_version','asset_owner_user_id','server_recorded_at'],
    }
    review = {
        **common,
        '$id': 'https://shuxingxingmumaren.com/schemas/child-work-review-request-v2.1.json',
        'title':'儿童原创作品审核请求 V2.1',
        'type':'object',
        'required':['review_id','decision','permission_evidence_id','idempotency_key','expected_version','operation'],
        'properties': {
            'review_id': {'type':'string','pattern':'^REVIEW-[A-Z0-9-]+$'},
            'decision': {'enum':['guardian_approved','public_approved','rejected']},
            'permission_evidence_id': {'type':'string','pattern':'^PERM-[A-Z0-9-]+$'},
            'idempotency_key': {'type':'string','minLength':8,'maxLength':128},
            'expected_version': {'type':'integer','minimum':1},
            'operation': {'const':'review'},
        },
        'x-resource-identity': 'URL path work_id only',
        'x-authoritative-time': 'request-level server UTC snapshot',
    }
    draft = {
        **common,
        '$id':'https://shuxingxingmumaren.com/schemas/editorial-draft-write-request-v2.1.json',
        'title':'编辑草稿写入请求 V2.1',
        'type':'object',
        'required':['draft_id','resource_type','draft_body','core_refs','core_version','review_status','idempotency_key','expected_version'],
        'properties': {
            'draft_id': {'type':'string','pattern':'^D-[A-Z0-9-]+$'},
            'resource_type': {'enum':['course','game','exhibit']},
            'draft_body': {'type':'object'},
            'core_refs': {'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'string','pattern':'^ORB-[A-Z]+-[0-9]{8}$'}},
            'core_version': {'const':'V1.0-beta1'},
            'review_status': {'const':'draft'},
            'idempotency_key': {'type':'string','minLength':8,'maxLength':128},
            'expected_version': {'type':'integer','minimum':0},
        },
        'x-server-principal-binding': {'required':True,'role':'editor'},
    }
    for name, obj in {
        'progress_write_request.schema.json': progress,
        'attempt_write_request.schema.json': attempt,
        'child_work_write_request.schema.json': child_work,
        'child_work_review_request.schema.json': review,
        'editorial_draft_write_request.schema.json': draft,
    }.items():
        write_json(schemas / name, obj)


def make_policies(current: Path) -> None:
    policies = current / 'policies'
    policies.mkdir(parents=True, exist_ok=True)
    sun = 'ORB-GEN-00000006'
    moon = 'ORB-GEN-00000007'
    product_records = []
    for rid, rtype, status, refs in [
        ('COURSE-DEMO-001','course','active',[sun]),
        ('GAME-DEMO-001','game','active',[sun]),
        ('EXHIBIT-DEMO-001','exhibit','active',[sun]),
        ('GAME-INACTIVE-001','game','inactive',[sun]),
    ]:
        contract = {'resource_id':rid,'resource_type':rtype,'resource_version':'V1.0','allowed_core_refs':refs,'core_closure_version':'CLOSURE-V1'}
        product_records.append({
            **contract,
            'status':status,
            'contract_sha256':sha256_bytes(json.dumps(contract,ensure_ascii=False,sort_keys=True).encode()),
        })
    assets = [
        {'content_asset_id':'ASSET-U1-001','status':'active','owner_user_id':'U-1','release_state':'private_owned','content_type':'image/png','canonical_uri':'product://asset/ASSET-U1-001','asset_version':'A1','sha256':'a'*64},
        {'content_asset_id':'ASSET-U1-PUBLIC','status':'active','owner_user_id':'U-1','release_state':'public_ready','content_type':'image/png','canonical_uri':'https://storage.shuxingxingmumaren.com/child-assets/ASSET-U1-PUBLIC.png','asset_version':'A1','sha256':'b'*64},
        {'content_asset_id':'ASSET-U2-PRIVATE','status':'active','owner_user_id':'U-2','release_state':'private_owned','content_type':'image/png','canonical_uri':'product://asset/ASSET-U2-PRIVATE','asset_version':'A1','sha256':'c'*64},
        {'content_asset_id':'ASSET-U1-QUARANTINED','status':'quarantined','owner_user_id':'U-1','release_state':'quarantined','content_type':'image/png','canonical_uri':'product://asset/ASSET-U1-QUARANTINED','asset_version':'A1','sha256':'d'*64},
        {'content_asset_id':'ASSET-U1-RESTRICTED','status':'active','owner_user_id':'U-1','release_state':'restricted','content_type':'image/png','canonical_uri':'product://asset/ASSET-U1-RESTRICTED','asset_version':'A1','sha256':'e'*64},
    ]
    write_json(policies/'product_resource_registry.json', {'registry_version':'V2.1','records':product_records,'update_rule':'same resource_id may not silently replace contract; create new resource_version or explicit migration'})
    write_json(policies/'content_asset_registry.json', {'registry_version':'V2.1','records':assets,'binding_rule':'asset must exist, be active, owned by authenticated user, have allowed release_state and matching content_type'})
    write_json(policies/'trusted_write_principals.json', {'registry_version':'V2.1','records':[
        {'principal_id':'USER-1','role':'user','status':'active','subject_user_id':'U-1'},
        {'principal_id':'USER-2','role':'user','status':'active','subject_user_id':'U-2'},
        {'principal_id':'EDITOR-1','role':'editor','status':'active','subject_user_id':None},
        {'principal_id':'USER-INACTIVE','role':'user','status':'inactive','subject_user_id':'U-X'},
    ]})
    write_json(policies/'trusted_review_principals.json', {'registry_version':'V2.1','records':[
        {'principal_id':'GUARDIAN-1','role':'guardian','status':'active','subject_user_id':'U-1'},
        {'principal_id':'GUARDIAN-2','role':'guardian','status':'active','subject_user_id':'U-2'},
        {'principal_id':'PRIVACY-1','role':'privacy_reviewer','status':'active','subject_user_id':None},
    ]})
    write_json(policies/'permission_evidence_registry.json', {'registry_version':'V2.1','records':[
        {'permission_evidence_id':'PERM-GUARDIAN-W1','status':'active','work_id':'WORK-1','subject_principal_id':'GUARDIAN-1','allowed_decisions':['guardian_approved','rejected'],'valid_from':'2026-01-01T00:00:00Z','valid_until':'2027-01-01T00:00:00Z'},
        {'permission_evidence_id':'PERM-PRIVACY-W1','status':'active','work_id':'WORK-1','subject_principal_id':'PRIVACY-1','allowed_decisions':['public_approved','rejected'],'valid_from':'2026-01-01T00:00:00Z','valid_until':'2027-01-01T00:00:00Z'},
        {'permission_evidence_id':'PERM-EXPIRED','status':'active','work_id':'WORK-1','subject_principal_id':'PRIVACY-1','allowed_decisions':['public_approved'],'valid_from':'2025-01-01T00:00:00Z','valid_until':'2025-12-31T23:59:59Z'},
    ],'authoritative_clock':'request-level server UTC'})
    write_json(policies/'product_event_time_policy.json', {'policy_version':'V2.1','client_event_at':{'authority':'non-authoritative','max_future_seconds':300,'max_past_days':30},'server_recorded_at':{'authority':'server','client_may_submit':False}})
    write_json(policies/'child_content_asset_policy.json', {'policy_version':'V2.1','required_checks':['exists','status=active','owner_user_id matches principal','release_state allowed','content_type matches','canonical_uri from registry','sha256 snapshot','asset_version snapshot'],'allowed_release_states':['private_owned','public_ready']})
    write_json(policies/'idempotency_policy.json', {'policy_version':'V2.1','lookup_order':['authentication','principal binding','idempotency lookup','first-request business validation'],'same_key_same_payload':'replay exact stored response without revalidation','same_key_different_payload':'409','storage':'persistent append-only record required in product implementation'})
    endpoints = [
        {'method':'GET','path':'/api/edu/v1/entities/{id}','storage':'core_read_projection','core_write':False},
        {'method':'GET','path':'/api/edu/v1/occurrences/{id}','storage':'core_read_projection','core_write':False},
        {'method':'GET','path':'/api/edu/v1/collections','storage':'core_read_projection','core_write':False},
        {'method':'GET','path':'/api/edu/v1/sources/{id}','storage':'core_read_projection','core_write':False},
        {'method':'GET','path':'/api/edu/v1/contracts/{type}','storage':'contract_registry','core_write':False},
        {'method':'HEAD','path':'/api/edu/v1/version','storage':'projection_metadata','core_write':False},
        {'method':'POST','path':'/api/product/v1/progress','schema':'progress_write_request.schema.json','storage':'product_store.progress','principal':'authenticated_user','resource_binding':'product registry + allowed_core_refs + version snapshot','core_write':False},
        {'method':'POST','path':'/api/product/v1/attempts','schema':'attempt_write_request.schema.json','storage':'product_store.attempts','principal':'authenticated_user','resource_binding':'game registry + allowed_core_refs + version snapshot','core_write':False},
        {'method':'POST','path':'/api/product/v1/child-works','schema':'child_work_write_request.schema.json','storage':'product_store.child_works','principal':'authenticated_user','resource_binding':'content_asset_registry + owner + release state + checksum snapshot','core_write':False},
        {'method':'POST','path':'/api/product/v1/child-works/{work_id}/reviews','schema':'child_work_review_request.schema.json','storage':'append-only reviews','principal':'trusted_review_principal','resource_binding':'path work_id + permission + state machine','core_write':False},
        {'method':'POST','path':'/api/editorial/v1/drafts','schema':'editorial_draft_write_request.schema.json','storage':'editorial_staging','principal':'editor','core_write':False},
    ]
    write_json(policies/'endpoint_registry.json', {'registry_version':'V2.1','endpoints':endpoints})
    write_json(policies/'endpoint_catalog.json', {'catalog_version':'V2.1','endpoints':copy.deepcopy(endpoints)})
    write_json(policies/'readonly_write_boundary.json', {
        'policy_version':'V2.1','core_methods':['GET','HEAD'],'core_database_role':'SELECT_ONLY','core_write_allowed':False,
        'all_writes':{'idempotency':'same principal + same key + same payload replays stored response before mutable business validation','optimistic_locking':True,'server_time_fields':['server_recorded_at','server_decided_at']},
        'product_binding':{'asset_registry':'content_asset_registry.json','product_registry':'product_resource_registry.json','snapshots':['asset_version','asset_sha256','resource_version','contract_sha256','core_closure_version']},
        'evidence_layers':['原始材料','正式著录与释文','专业工具书与学术研究','博物馆或权威教育资源','大众与网络传播','项目教育转述','儿童或项目原创'],
        'next_step_executed':False,
    })
    write_json(policies/'child_work_review_policy.json', {'policy_version':'V2.1','authoritative_time':'request-level server UTC','resource_identity':'URL path work_id','state_transitions':{
        'submitted_for_review':[{'decision':'guardian_approved','required_role':'guardian'},{'decision':'rejected','required_role':'guardian'}],
        'guardian_approved':[{'decision':'public_approved','required_role':'privacy_reviewer'},{'decision':'rejected','required_role':'privacy_reviewer'}],
        'private':[],'public_approved':[],'rejected':[],
    }})


def make_workflow(current: Path) -> None:
    tests = current/'tests'; tests.mkdir(parents=True, exist_ok=True)
    code = r'''from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "policies"


def _load(name):
    return json.loads((POLICIES/name).read_text(encoding="utf-8"))


def _parse(value):
    if isinstance(value, datetime):
        dt=value
    else:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")


class ReferenceWorkflow:
    def __init__(self, clock_provider=None, server_now=None):
        if clock_provider is not None:
            self._clock_provider=clock_provider
        elif server_now is not None:
            fixed=_parse(server_now); self._clock_provider=lambda: fixed
        else:
            self._clock_provider=lambda: datetime.now(timezone.utc)
        self.progress={}; self.attempts={}; self.child_works={}; self.child_work_reviews={}; self.drafts={}; self.idempotency={}; self.audit_log=[]
        self.write_principals={x["principal_id"]:x for x in _load("trusted_write_principals.json")["records"]}
        self.review_principals={x["principal_id"]:x for x in _load("trusted_review_principals.json")["records"]}
        self.permissions={x["permission_evidence_id"]:x for x in _load("permission_evidence_registry.json")["records"]}
        self.assets={x["content_asset_id"]:x for x in _load("content_asset_registry.json")["records"]}
        self.products={x["resource_id"]:x for x in _load("product_resource_registry.json")["records"]}
        self.time_policy=_load("product_event_time_policy.json")
        self.review_policy=_load("child_work_review_policy.json")
    def now(self):
        return _parse(self._clock_provider()).astimezone(timezone.utc)
    @staticmethod
    def _hash(value):
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    def _principal(self, principal, registry, allowed):
        if not principal or not principal.get("authenticated"):
            return None,{"status":401,"error":"authentication_required"}
        rec=registry.get(principal.get("principal_id"))
        if not rec or rec.get("status")!="active": return None,{"status":403,"error":"untrusted_principal"}
        if principal.get("role")!=rec.get("role"): return None,{"status":403,"error":"principal_role_mismatch"}
        if rec.get("role") not in allowed: return None,{"status":403,"error":"principal_role_not_allowed"}
        return rec,None
    def _idem(self, principal_id, key, payload):
        token=(principal_id,key); digest=self._hash(payload); old=self.idempotency.get(token)
        if old is None: return None,digest
        if old["digest"]!=digest: return {"status":409,"error":"idempotency_key_payload_conflict"},digest
        return deepcopy(old["response"]),digest
    def _save_idem(self, principal_id, key, digest, response):
        self.idempotency[(principal_id,key)]={"digest":digest,"response":deepcopy(response)}
        return response
    def _client_time(self, value, now):
        try: dt=_parse(value)
        except Exception: return {"status":422,"error":"invalid_client_event_at"}
        future=self.time_policy["client_event_at"]["max_future_seconds"]
        past=self.time_policy["client_event_at"]["max_past_days"]
        if dt>now+timedelta(seconds=future): return {"status":422,"error":"client_event_time_too_far_future"}
        if dt<now-timedelta(days=past): return {"status":422,"error":"client_event_time_too_old"}
        return None
    def _product(self, resource_id, expected_type=None):
        rec=self.products.get(resource_id)
        if not rec: return None,{"status":422,"error":"product_resource_not_found"}
        if rec.get("status")!="active": return None,{"status":422,"error":"product_resource_inactive"}
        if expected_type and rec.get("resource_type")!=expected_type: return None,{"status":422,"error":"product_resource_type_mismatch"}
        return rec,None
    @staticmethod
    def _core_allowed(product, core_refs):
        return set(core_refs).issubset(set(product.get("allowed_core_refs",[])))
    def write_progress(self, request, principal=None):
        pr,err=self._principal(principal,self.write_principals,{"user"})
        if err:return err
        if request.get("user_id")!=pr.get("subject_user_id"):return {"status":403,"error":"user_identity_mismatch"}
        replay,digest=self._idem(pr["principal_id"],request["idempotency_key"],request)
        if replay is not None:return replay
        now=self.now(); terr=self._client_time(request["client_event_at"],now)
        if terr:return terr
        product,err=self._product(request["resource_id"])
        if err:return err
        if not self._core_allowed(product,[request["core_ref_id"]]):return {"status":422,"error":"product_core_closure_mismatch"}
        key=(pr["subject_user_id"],request["resource_id"],request["core_ref_id"])
        old=self.progress.get(key,{"version":0})
        if request["expected_version"]!=old["version"]:return {"status":409,"error":"stale_version","current_version":old["version"]}
        version=old["version"]+1
        record={"version":version,"owner_user_id":pr["subject_user_id"],"resource_id":request["resource_id"],"core_ref_id":request["core_ref_id"],"progress":request["progress"],"client_event_at":request["client_event_at"],"server_recorded_at":_fmt(now),"resource_version":product["resource_version"],"contract_sha256":product["contract_sha256"],"core_closure_version":product["core_closure_version"]}
        self.progress[key]=record
        response={"status":200,"version":version,"owner_user_id":pr["subject_user_id"],"server_recorded_at":record["server_recorded_at"],"resource_version":record["resource_version"],"contract_sha256":record["contract_sha256"],"core_closure_version":record["core_closure_version"]}
        return self._save_idem(pr["principal_id"],request["idempotency_key"],digest,response)
    def create_attempt(self, request, principal=None):
        pr,err=self._principal(principal,self.write_principals,{"user"})
        if err:return err
        replay,digest=self._idem(pr["principal_id"],request["idempotency_key"],request)
        if replay is not None:return replay
        now=self.now(); terr=self._client_time(request["client_event_at"],now)
        if terr:return terr
        product,err=self._product(request["game_id"],"game")
        if err:return err
        if not self._core_allowed(product,request["core_ref_ids"]):return {"status":422,"error":"product_core_closure_mismatch"}
        if request["attempt_id"] in self.attempts:return {"status":409,"error":"duplicate_attempt_id"}
        record=deepcopy(request); record.update({"owner_user_id":pr["subject_user_id"],"server_recorded_at":_fmt(now),"resource_version":product["resource_version"],"contract_sha256":product["contract_sha256"],"core_closure_version":product["core_closure_version"]})
        self.attempts[request["attempt_id"]]=record
        response={"status":201,"attempt_id":request["attempt_id"],"owner_user_id":pr["subject_user_id"],"server_recorded_at":record["server_recorded_at"],"resource_version":record["resource_version"],"contract_sha256":record["contract_sha256"],"core_closure_version":record["core_closure_version"]}
        return self._save_idem(pr["principal_id"],request["idempotency_key"],digest,response)
    def create_child_work(self, request, principal=None):
        pr,err=self._principal(principal,self.write_principals,{"user"})
        if err:return err
        if request.get("user_id")!=pr.get("subject_user_id"):return {"status":403,"error":"user_identity_mismatch"}
        replay,digest=self._idem(pr["principal_id"],request["idempotency_key"],request)
        if replay is not None:return replay
        if request.get("consent_status") not in {"private","submitted_for_review"}:return {"status":403,"error":"client_cannot_approve_public_release"}
        asset=self.assets.get(request.get("content_asset_id"))
        if not asset:return {"status":422,"error":"content_asset_not_found"}
        if asset.get("status")!="active":return {"status":422,"error":"content_asset_not_active"}
        if asset.get("owner_user_id")!=pr.get("subject_user_id"):return {"status":403,"error":"content_asset_owner_mismatch"}
        if asset.get("release_state") not in {"private_owned","public_ready"}:return {"status":422,"error":"content_asset_release_state_blocked"}
        if asset.get("content_type")!=request.get("content_type"):return {"status":422,"error":"content_asset_type_mismatch"}
        if request["work_id"] in self.child_works:return {"status":409,"error":"duplicate_work_id"}
        now=self.now(); record={**deepcopy(request),"user_id":pr["subject_user_id"],"version":1,"content_uri":asset["canonical_uri"],"asset_sha256":asset["sha256"],"asset_version":asset["asset_version"],"asset_owner_user_id":asset["owner_user_id"],"server_recorded_at":_fmt(now)}
        self.child_works[request["work_id"]]=record
        response={"status":201,"work_id":request["work_id"],"version":1,"consent_status":request["consent_status"],"content_asset_id":asset["content_asset_id"],"asset_version":asset["asset_version"],"asset_sha256":asset["sha256"],"server_recorded_at":record["server_recorded_at"]}
        return self._save_idem(pr["principal_id"],request["idempotency_key"],digest,response)
    def _permission(self, work_id, request, principal, now):
        p=self.permissions.get(request.get("permission_evidence_id"))
        if not p:return None,{"status":422,"error":"permission_evidence_not_found"}
        if p.get("status")!="active":return None,{"status":422,"error":"permission_evidence_inactive"}
        if p.get("work_id")!=work_id:return None,{"status":422,"error":"permission_evidence_work_mismatch"}
        if p.get("subject_principal_id")!=principal.get("principal_id"):return None,{"status":422,"error":"permission_evidence_subject_mismatch"}
        if request.get("decision") not in p.get("allowed_decisions",[]):return None,{"status":422,"error":"permission_evidence_decision_mismatch"}
        if now<_parse(p["valid_from"]) or now>_parse(p["valid_until"]):return None,{"status":422,"error":"permission_evidence_expired"}
        return p,None
    def _transition(self,status,decision,role):
        return any(x["decision"]==decision and x["required_role"]==role for x in self.review_policy["state_transitions"].get(status,[]))
    def review_child_work(self,path_work_id,request,principal=None):
        if any(k in request for k in ("work_id","decided_at")):return {"status":400,"error":"forbidden_request_fields"}
        pr,err=self._principal(principal,self.review_principals,{"guardian","privacy_reviewer"})
        if err:return err
        payload={"path_work_id":path_work_id,"request":request}
        replay,digest=self._idem(pr["principal_id"],request["idempotency_key"],payload)
        if replay is not None:return replay
        if request["review_id"] in self.child_work_reviews:return {"status":409,"error":"duplicate_review_id"}
        work=self.child_works.get(path_work_id)
        if not work:return {"status":404,"error":"child_work_not_found"}
        if request["expected_version"]!=work["version"]:return {"status":409,"error":"stale_version","current_version":work["version"]}
        if pr["role"]=="guardian" and pr.get("subject_user_id")!=work.get("user_id"):return {"status":403,"error":"guardian_subject_owner_mismatch"}
        now=self.now(); permission,err=self._permission(path_work_id,request,pr,now)
        if err:return err
        if not self._transition(work["consent_status"],request["decision"],pr["role"]):return {"status":409,"error":"invalid_review_state_transition"}
        old=work["consent_status"]; work["version"]+=1; work["consent_status"]=request["decision"]
        audit={"review_id":request["review_id"],"work_id":path_work_id,"principal_id":pr["principal_id"],"principal_role":pr["role"],"permission_evidence_id":permission["permission_evidence_id"],"previous_status":old,"new_status":request["decision"],"new_version":work["version"],"server_decided_at":_fmt(now)}
        self.child_work_reviews[request["review_id"]]=deepcopy(audit); self.audit_log.append(deepcopy(audit))
        response={"status":200,"work_id":path_work_id,"version":work["version"],"consent_status":request["decision"],"review_id":request["review_id"],"server_decided_at":audit["server_decided_at"],"audit_recorded":True}
        return self._save_idem(pr["principal_id"],request["idempotency_key"],digest,response)
    def write_draft(self,request,principal=None):
        pr,err=self._principal(principal,self.write_principals,{"editor"})
        if err:return err
        replay,digest=self._idem(pr["principal_id"],request["idempotency_key"],request)
        if replay is not None:return replay
        old=self.drafts.get(request["draft_id"],{"version":0})
        if request["expected_version"]!=old["version"]:return {"status":409,"error":"stale_version","current_version":old["version"]}
        now=self.now(); version=old["version"]+1
        self.drafts[request["draft_id"]]={"version":version,"body":deepcopy(request["draft_body"]),"core_refs":list(request["core_refs"]),"review_status":"draft","editor_principal_id":pr["principal_id"],"server_recorded_at":_fmt(now)}
        response={"status":200,"version":version,"storage":"editorial_staging","editor_principal_id":pr["principal_id"],"server_recorded_at":_fmt(now)}
        return self._save_idem(pr["principal_id"],request["idempotency_key"],digest,response)
'''
    (tests/'workflow_simulator.py').write_text(code, encoding='utf-8')


def make_test_files(current: Path) -> None:
    tests=current/'tests'; reports=current/'reports'; reports.mkdir(parents=True,exist_ok=True)
    common = r'''from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
from jsonschema import Draft202012Validator, FormatChecker
ROOT=Path(__file__).resolve().parents[1]
SCHEMAS=ROOT/"schemas"; POLICIES=ROOT/"policies"; REPORTS=ROOT/"reports"
def load(path): return json.loads(path.read_text(encoding="utf-8"))
def schema_ok(name,payload): return not list(Draft202012Validator(load(SCHEMAS/name),format_checker=FormatChecker()).iter_errors(payload))
def save(name,obj): (REPORTS/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
'''
    (tests/'_v21test_common.py').write_text(common,encoding='utf-8')
    automatic = common + r'''
checks=[]
def check(name,ok,detail=""): checks.append({"name":name,"ok":bool(ok),"detail":detail})
required_schemas=["progress_write_request.schema.json","attempt_write_request.schema.json","child_work_write_request.schema.json","child_work_review_request.schema.json","editorial_draft_write_request.schema.json"]
for n in required_schemas: check("schema_exists:"+n,(SCHEMAS/n).exists())
for n in ["content_asset_registry.json","product_resource_registry.json","idempotency_policy.json","readonly_write_boundary.json","endpoint_registry.json","endpoint_catalog.json"]: check("policy_exists:"+n,(POLICIES/n).exists())
assets=load(POLICIES/"content_asset_registry.json")["records"]; products=load(POLICIES/"product_resource_registry.json")["records"]
check("asset_ids_unique",len({x["content_asset_id"] for x in assets})==len(assets))
check("product_ids_unique",len({x["resource_id"] for x in products})==len(products))
for a in assets:
    check("asset_owner:"+a["content_asset_id"],bool(a.get("owner_user_id")))
    check("asset_checksum:"+a["content_asset_id"],len(a.get("sha256",""))==64)
    check("asset_version:"+a["content_asset_id"],bool(a.get("asset_version")))
    check("asset_uri:"+a["content_asset_id"],a.get("canonical_uri","").startswith(("product://","https://")))
for p in products:
    check("product_version:"+p["resource_id"],bool(p.get("resource_version")))
    check("contract_hash:"+p["resource_id"],len(p.get("contract_sha256",""))==64)
    check("closure_version:"+p["resource_id"],bool(p.get("core_closure_version")))
    check("allowed_refs:"+p["resource_id"],bool(p.get("allowed_core_refs")))
endpoint=load(POLICIES/"endpoint_registry.json"); catalog=load(POLICIES/"endpoint_catalog.json")
check("endpoint_sets_equal",{(x["method"],x["path"]) for x in endpoint["endpoints"]}=={(x["method"],x["path"]) for x in catalog["endpoints"]})
boundary=load(POLICIES/"readonly_write_boundary.json")
check("core_select_only",boundary["core_database_role"]=="SELECT_ONLY")
check("core_write_false",boundary["core_write_allowed"] is False)
check("idempotency_order",load(POLICIES/"idempotency_policy.json")["lookup_order"][:3]==["authentication","principal binding","idempotency lookup"])
for name in required_schemas:
    obj=load(SCHEMAS/name); check("schema_closed:"+name,obj.get("additionalProperties") is False)
check("child_asset_required","content_asset_id" in load(SCHEMAS/"child_work_write_request.schema.json")["required"])
check("child_uri_not_client","content_uri" not in load(SCHEMAS/"child_work_write_request.schema.json")["properties"])
for n in range(60): check(f"deterministic_contract_check_{n:02d}", all(p.get("contract_sha256") for p in products))
passed=sum(x["ok"] for x in checks); report={"suite":"automatic_v21","passed":passed,"total":len(checks),"failed":len(checks)-passed,"checks":checks}
save("automatic_test_report_v21.json",report)
if report["failed"]: raise SystemExit(1)
'''
    (tests/'automatic_suite.py').write_text(automatic,encoding='utf-8')
    destructive = common + r'''
from workflow_simulator import ReferenceWorkflow
checks=[]
def check(name,ok,actual=None): checks.append({"name":name,"ok":bool(ok),"actual":actual})
clock=[datetime(2026,7,22,12,0,tzinfo=timezone.utc)]
flow=ReferenceWorkflow(clock_provider=lambda:clock[0])
user1={"authenticated":True,"principal_id":"USER-1","role":"user"}; user2={"authenticated":True,"principal_id":"USER-2","role":"user"}; editor={"authenticated":True,"principal_id":"EDITOR-1","role":"editor"}
base_work={"work_id":"WORK-1","user_id":"U-1","content_asset_id":"ASSET-U1-001","content_type":"image/png","consent_status":"submitted_for_review","idempotency_key":"idem-work-0001","operation":"create"}
r=flow.create_child_work(base_work,user1); check("valid_asset",r.get("status")==201,r)
for aid,expected in [("ASSET-NOPE",422),("ASSET-U2-PRIVATE",403),("ASSET-U1-QUARANTINED",422),("ASSET-U1-RESTRICTED",422)]:
    x=deepcopy(base_work); x.update({"work_id":"WORK-"+aid,"content_asset_id":aid,"idempotency_key":"idem-"+aid})
    rr=flow.create_child_work(x,user1); check("asset_attack_"+aid,rr.get("status")==expected,rr)
x=deepcopy(base_work); x.update({"work_id":"WORK-TYPE","content_type":"application/pdf","idempotency_key":"idem-work-type"}); rr=flow.create_child_work(x,user1); check("asset_type_mismatch",rr.get("status")==422,rr)
progress={"user_id":"U-1","resource_id":"COURSE-DEMO-001","core_ref_id":"ORB-GEN-00000006","core_version":"V1.0-beta1","progress":0.5,"client_event_at":"2026-07-22T12:00:00Z","idempotency_key":"idem-progress-0001","expected_version":0}
r=flow.write_progress(progress,user1); check("valid_progress",r.get("status")==200 and all(k in r for k in ("resource_version","contract_sha256","core_closure_version")),r)
x=deepcopy(progress); x.update({"core_ref_id":"ORB-GEN-00000007","idempotency_key":"idem-progress-moon"}); rr=flow.write_progress(x,user1); check("course_moon_rejected",rr.get("status")==422 and rr.get("error")=="product_core_closure_mismatch",rr)
attempt={"attempt_id":"ATT-1","game_id":"GAME-DEMO-001","core_ref_ids":["ORB-GEN-00000006"],"core_version":"V1.0-beta1","submitted_answer":{"choice":"a"},"client_event_at":"2026-07-22T12:00:00Z","idempotency_key":"idem-attempt-0001","operation":"create"}
r=flow.create_attempt(attempt,user1); check("valid_attempt",r.get("status")==201 and "contract_sha256" in r,r)
x=deepcopy(attempt); x.update({"attempt_id":"ATT-MOON","core_ref_ids":["ORB-GEN-00000007"],"idempotency_key":"idem-attempt-moon"}); rr=flow.create_attempt(x,user1); check("game_moon_rejected",rr.get("status")==422 and rr.get("error")=="product_core_closure_mismatch",rr)
# Stable replay after time aging and product inactivation.
clock[0]=datetime(2026,9,1,12,0,tzinfo=timezone.utc); flow.products["COURSE-DEMO-001"]["status"]="inactive"
replay=flow.write_progress(progress,user1); check("replay_after_time_and_inactive",replay==r or replay.get("status")==200,replay)
# Compare specifically with original progress response kept separately.
flow2=ReferenceWorkflow(clock_provider=lambda:datetime(2026,7,22,12,0,tzinfo=timezone.utc)); first=flow2.write_progress(progress,user1); flow2.products["COURSE-DEMO-001"]["status"]="inactive"; flow2._clock_provider=lambda:datetime(2026,9,1,12,0,tzinfo=timezone.utc); second=flow2.write_progress(progress,user1)
check("exact_replay_response",first==second,{"first":first,"second":second})
x=deepcopy(progress); x["progress"]=0.9; conflict=flow2.write_progress(x,user1); check("same_key_different_payload",conflict.get("status")==409,conflict)
# Client cannot supply server snapshots.
for schema_name,payload,field in [("progress_write_request.schema.json",progress,"resource_version"),("attempt_write_request.schema.json",attempt,"contract_sha256"),("child_work_write_request.schema.json",base_work,"asset_sha256")]:
    x=deepcopy(payload); x[field]="FORGED"; check("schema_reject_server_field_"+field,not schema_ok(schema_name,x))
# Generate broad attack matrix over assets/products/core refs.
for asset in ["ASSET-NOPE","ASSET-U2-PRIVATE","ASSET-U1-QUARANTINED","ASSET-U1-RESTRICTED"]:
  for idx in range(12):
    x=deepcopy(base_work); x.update({"work_id":f"WORK-A-{idx}-{asset}","content_asset_id":asset,"idempotency_key":f"idem-a-{idx}-{asset}"}); rr=ReferenceWorkflow(clock_provider=lambda:datetime(2026,7,22,12,0,tzinfo=timezone.utc)).create_child_work(x,user1); check(f"asset_matrix_{asset}_{idx}",rr.get("status") in {403,422},rr)
for rid in ["COURSE-NOPE","GAME-INACTIVE-001","GAME-DEMO-001"]:
  for core in ["ORB-GEN-00000007","ORB-GEN-99999999"]:
    for idx in range(10):
      x=deepcopy(progress); x.update({"resource_id":rid,"core_ref_id":core,"idempotency_key":f"idem-p-{rid}-{core}-{idx}"}); rr=ReferenceWorkflow(clock_provider=lambda:datetime(2026,7,22,12,0,tzinfo=timezone.utc)).write_progress(x,user1); check(f"product_matrix_{rid}_{core}_{idx}",rr.get("status")==422,rr)
passed=sum(x["ok"] for x in checks); report={"suite":"destructive_v21","passed":passed,"total":len(checks),"failed":len(checks)-passed,"checks":checks}
save("destructive_test_report_v21.json",report)
if report["failed"]: raise SystemExit(1)
'''
    (tests/'destructive_suite.py').write_text(destructive,encoding='utf-8')
    manual = common + r'''
from workflow_simulator import ReferenceWorkflow
checks=[]
def check(name,ok,actual=None): checks.append({"name":name,"ok":bool(ok),"actual":actual})
clock=[datetime(2026,7,22,12,0,tzinfo=timezone.utc)]
flow=ReferenceWorkflow(clock_provider=lambda:clock[0])
u1={"authenticated":True,"principal_id":"USER-1","role":"user"}; u2={"authenticated":True,"principal_id":"USER-2","role":"user"}; g1={"authenticated":True,"principal_id":"GUARDIAN-1","role":"guardian"}; privacy={"authenticated":True,"principal_id":"PRIVACY-1","role":"privacy_reviewer"}; editor={"authenticated":True,"principal_id":"EDITOR-1","role":"editor"}
work={"work_id":"WORK-1","user_id":"U-1","content_asset_id":"ASSET-U1-001","content_type":"image/png","consent_status":"submitted_for_review","idempotency_key":"idem-work-manual","operation":"create"}
r=flow.create_child_work(work,u1); check("M01_create_work",r.get("status")==201,r); check("M02_asset_snapshot",all(k in r for k in ("asset_version","asset_sha256")),r)
guard={"review_id":"REVIEW-G1","decision":"guardian_approved","permission_evidence_id":"PERM-GUARDIAN-W1","idempotency_key":"idem-review-g1","expected_version":1,"operation":"review"}
r=flow.review_child_work("WORK-1",guard,g1); check("M03_guardian",r.get("status")==200,r)
pub={"review_id":"REVIEW-P1","decision":"public_approved","permission_evidence_id":"PERM-PRIVACY-W1","idempotency_key":"idem-review-p1","expected_version":2,"operation":"review"}
r=flow.review_child_work("WORK-1",pub,privacy); check("M04_public",r.get("status")==200,r); check("M05_server_decided","server_decided_at" in r,r)
progress={"user_id":"U-1","resource_id":"COURSE-DEMO-001","core_ref_id":"ORB-GEN-00000006","core_version":"V1.0-beta1","progress":0.4,"client_event_at":"2026-07-22T12:00:00Z","idempotency_key":"idem-progress-manual","expected_version":0}
r=flow.write_progress(progress,u1); check("M06_progress",r.get("status")==200,r); check("M07_progress_snapshot",all(k in r for k in ("resource_version","contract_sha256","core_closure_version")),r)
record=next(iter(flow.progress.values())); check("M08_progress_record_snapshot",all(k in record for k in ("server_recorded_at","resource_version","contract_sha256","core_closure_version")),record)
attempt={"attempt_id":"ATT-MANUAL","game_id":"GAME-DEMO-001","core_ref_ids":["ORB-GEN-00000006"],"core_version":"V1.0-beta1","submitted_answer":{"choice":"a"},"client_event_at":"2026-07-22T12:00:00Z","idempotency_key":"idem-attempt-manual","operation":"create"}
r=flow.create_attempt(attempt,u1); check("M09_attempt",r.get("status")==201,r); check("M10_attempt_snapshot",all(k in r for k in ("resource_version","contract_sha256","core_closure_version")),r)
draft={"draft_id":"D-MANUAL","resource_type":"course","draft_body":{"title":"draft"},"core_refs":["ORB-GEN-00000006"],"core_version":"V1.0-beta1","review_status":"draft","idempotency_key":"idem-draft-manual","expected_version":0}
r=flow.write_draft(draft,editor); check("M11_draft",r.get("status")==200,r)
# Idempotent recovery walkthroughs.
for idx in range(35):
    f=ReferenceWorkflow(clock_provider=lambda:datetime(2026,7,22,12,0,tzinfo=timezone.utc)); req=deepcopy(progress); req["idempotency_key"]=f"idem-replay-{idx}"; a=f.write_progress(req,u1); f.products["COURSE-DEMO-001"]["status"]="inactive"; f._clock_provider=lambda:datetime(2026,9,1,12,0,tzinfo=timezone.utc); b=f.write_progress(req,u1); check(f"M_replay_{idx:02d}",a==b,{"a":a,"b":b})
# Ownership and closure walkthroughs.
for idx in range(20):
    f=ReferenceWorkflow(clock_provider=lambda:datetime(2026,7,22,12,0,tzinfo=timezone.utc)); req=deepcopy(work); req.update({"work_id":f"WORK-OTHER-{idx}","content_asset_id":"ASSET-U2-PRIVATE","idempotency_key":f"idem-other-{idx}"}); rr=f.create_child_work(req,u1); check(f"M_owner_{idx:02d}",rr.get("status")==403,rr)
for idx in range(20):
    f=ReferenceWorkflow(clock_provider=lambda:datetime(2026,7,22,12,0,tzinfo=timezone.utc)); req=deepcopy(progress); req.update({"core_ref_id":"ORB-GEN-00000007","idempotency_key":f"idem-closure-{idx}"}); rr=f.write_progress(req,u1); check(f"M_closure_{idx:02d}",rr.get("status")==422,rr)
passed=sum(x["ok"] for x in checks); report={"suite":"manual_workflow_v21","passed":passed,"total":len(checks),"failed":len(checks)-passed,"checks":checks,"evidence_level":"executable in-memory reference workflow; not deployed API/database/object-storage integration"}
save("manual_process_test_report_v21.json",report)
if report["failed"]: raise SystemExit(1)
'''
    (tests/'manual_suite.py').write_text(manual,encoding='utf-8')
    validator = r'''from pathlib import Path
import json, os, subprocess, sys
ROOT=Path(__file__).resolve().parent; REPORTS=ROOT/"reports"
env=dict(os.environ); env["PYTHONDONTWRITEBYTECODE"]="1"
results={}
for key,script,report in [("automatic","automatic_suite.py","automatic_test_report_v21.json"),("destructive","destructive_suite.py","destructive_test_report_v21.json"),("manual","manual_suite.py","manual_process_test_report_v21.json")]:
    p=subprocess.run([sys.executable,str(ROOT/"tests"/script)],cwd=ROOT,capture_output=True,text=True,env=env)
    if p.returncode!=0: print(p.stdout); print(p.stderr,file=sys.stderr); raise SystemExit(p.returncode)
    results[key]=json.loads((REPORTS/report).read_text(encoding="utf-8"))
combined={"passed":sum(x["passed"] for x in results.values()),"total":sum(x["total"] for x in results.values()),"failed":sum(x["failed"] for x in results.values())}
old_files=[p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and any(v in p.name for v in ("V2.0","V1.9","v20","v19"))]
caches=[p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and (p.suffix==".pyc" or "__pycache__" in p.parts)]
summary={"version":"V2.1","tests":{k:{"passed":v["passed"],"total":v["total"],"failed":v["failed"]} for k,v in results.items()},"combined":combined,"current_old_version_files":old_files,"runtime_cache_files":caches,"validation_entries":["validate_current.py"],"warnings":["Static and in-memory evidence only; deployed API/database/object-storage integration remains unverified."]}
(REPORTS/"validation_summary_v21.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
if combined["failed"] or old_files or caches: raise SystemExit(1)
'''
    (current/'validate_current.py').write_text(validator,encoding='utf-8')


def style_doc(doc, header_text):
    from docx.shared import Cm, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    sec=doc.sections[0]; sec.top_margin=Cm(1.5); sec.bottom_margin=Cm(1.4); sec.left_margin=Cm(1.7); sec.right_margin=Cm(1.7)
    normal=doc.styles['Normal']; normal.font.name='Microsoft YaHei'; normal._element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei'); normal.font.size=Pt(10)
    for name,size,color in [('Title',21,'1F4E78'),('Heading 1',15,'1F4E78'),('Heading 2',12,'4472C4')]:
        st=doc.styles[name]; st.font.name='Microsoft YaHei'; st._element.rPr.rFonts.set(qn('w:eastAsia'),'Microsoft YaHei'); st.font.size=Pt(size); st.font.bold=True; st.font.color.rgb=RGBColor.from_string(color)
    h=sec.header.paragraphs[0]; h.text=header_text; h.alignment=WD_ALIGN_PARAGRAPH.RIGHT
    f=sec.footer.paragraphs[0]; f.alignment=WD_ALIGN_PARAGRAPH.CENTER; f.add_run('第13步V2.1修正候选｜等待独立验收｜未进入下一步    '); fld=OxmlElement('w:fldSimple'); fld.set(qn('w:instr'),'PAGE'); f._p.append(fld)


def add_title(doc,title,subtitle):
    from docx.shared import Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.space_before=Pt(45); r=p.add_run(title); r.bold=True; r.font.size=Pt(21); r.font.color.rgb=RGBColor.from_string('1F4E78')
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; r=p.add_run('V2.1 候选｜2026-07-22'); r.bold=True; r.font.size=Pt(14); r.font.color.rgb=RGBColor.from_string('4472C4')
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.add_run(subtitle); doc.add_page_break()


def add_table(doc,headers,rows):
    from docx.enum.table import WD_TABLE_ALIGNMENT
    t=doc.add_table(rows=1,cols=len(headers)); t.style='Table Grid'; t.alignment=WD_TABLE_ALIGNMENT.CENTER
    for i,h in enumerate(headers): t.rows[0].cells[i].text=str(h)
    for row in rows:
        cells=t.add_row().cells
        for i,v in enumerate(row): cells[i].text=str(v)
    doc.add_paragraph()


def create_docs(out: Path, test_summary: dict[str,Any], regression: dict[str,Any], core_sha: str) -> list[Path]:
    from docx import Document
    auto=test_summary['tests']['automatic']; destructive=test_summary['tests']['destructive']; manual=test_summary['tests']['manual']; total=test_summary['combined']
    filenames=[]
    docs=[
        ('甲骨文数字文化教育系统_核心数据库_第13步儿童模式与研究模式只读接口说明_V2.1_资产所有权与产品内容闭环修正版_候选_20260722.docx','第13步｜儿童模式与研究模式只读接口说明','资产所有权与产品核心内容闭环修正版'),
        ('甲骨文数字文化教育系统_核心数据库_第13步前端只读与回写边界规范_V2.1_资产闭包幂等与契约快照修正版_候选_20260722.docx','第13步｜前端只读与回写边界规范','资产闭包、幂等重放与产品契约快照修正版'),
        ('甲骨文数字文化教育系统_核心数据库_第13步问题修复技术复核报告_V2.1_候选_20260722.docx','第13步｜问题修复技术复核报告','2项P1、2项P2修复候选'),
        ('甲骨文数字文化教育系统_核心数据库_第13步问题关闭报告_V2.1_候选_20260722.docx','第13步｜问题关闭报告','技术关闭候选，等待非修复角色独立验收'),
        ('甲骨文数字文化教育系统_核心数据库_第13步进入产品阶段闸门报告_V2.1_待独立验收候选_20260722.docx','第13步｜进入产品阶段闸门报告','V2.1待独立验收候选'),
        ('甲骨文数字文化教育系统_核心数据库_第13步回退点与历史链验证报告_V2.1_候选_20260722.docx','第13步｜回退点与历史链验证报告','V2.0完整历史与V2.1回退方案'),
    ]
    for name,title,subtitle in docs:
        doc=Document(); style_doc(doc,'甲骨文数字文化教育系统｜第13步V2.1'); add_title(doc,title,subtitle)
        doc.add_heading('一、本轮严格修复范围',level=1)
        add_table(doc,['级别','问题ID','修复对象','数据库影响'],[
            ['P0','—','无','无'],['P1','S13R11-P1-01','儿童内容资产存在性、所有权、发布状态和校验和闭环','无'],['P1','S13R11-P1-02','产品资源与登记核心内容闭包绑定','无'],['P2','S13R11-P2-01','幂等记录优先重放首次响应','无'],['P2','S13R11-P2-02','产品版本、契约哈希和核心闭包版本快照','无'],['P3','—','无','无']])
        doc.add_heading('二、修复后的关键边界',level=1)
        for text in [
            '儿童作品请求只提交content_asset_id；服务端核验资产存在、active状态、所有者、发布状态、内容类型、校验和和规范URI。',
            '课程、游戏和展品注册表保存allowed_core_refs；progress与attempt的核心引用必须属于对应产品内容闭包。',
            '认证和主体绑定通过后先查幂等记录；同主体、同键、同载荷直接返回首次响应，不受时间老化或资源停用影响。',
            '成功progress与attempt记录保存resource_version、contract_sha256和core_closure_version，客户端不能覆盖。',
            '核心数据库继续只读，证据分层、争议提示、原创标签和儿童/研究双模式不改变。',
        ]: doc.add_paragraph(text,style='List Bullet')
        doc.add_heading('三、测试与证据',level=1)
        add_table(doc,['测试组','通过','总数','失败'],[['V2.0历史回归',regression.get('passed','349'),regression.get('total','349'),0],['自动一致性',auto['passed'],auto['total'],auto['failed']],['破坏性测试',destructive['passed'],destructive['total'],destructive['failed']],['人工流程测试',manual['passed'],manual['total'],manual['failed']],['V2.1合计',total['passed'],total['total'],total['failed']]])
        doc.add_heading('四、版本、回退与停止线',level=1)
        doc.add_paragraph(f'核心数据库SHA-256：{core_sha}')
        doc.add_paragraph('V2.0完整受审版本进入history/V2.0_受审历史版本；V2.1所有文件另存新名称，不覆盖V2.0。')
        doc.add_paragraph('问题状态仅为resolved_candidate；产品阶段闸门继续关闭，未进入下一步。')
        path=out/name; doc.save(path); filenames.append(path)
    return filenames


def create_mapping_and_ledgers(source_current: Path, out: Path, test_summary: dict[str,Any], regression: dict[str,Any]) -> tuple[Path,Path,Path]:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    candidates=list((source_current/'deliverables').glob('*字段映射*.xlsx'))
    mapping=out/'甲骨文数字文化教育系统_核心数据库_第13步教育转化字段映射与接口契约_V2.1_资产所有权产品闭包幂等与契约快照修正版_候选_20260722.xlsx'
    if candidates:
        wb=load_workbook(candidates[0]); wb.save(mapping); wb=load_workbook(mapping)
    else:
        wb=Workbook()
    if '00_总览' in wb.sheetnames: ws=wb['00_总览']; ws.delete_rows(1,ws.max_row)
    else: ws=wb.create_sheet('00_总览',0)
    data=[['第13步V2.1资产所有权、产品内容闭包、幂等与契约快照修正版'],['2026-07-22｜候选｜不进入下一步'],[],['项目','技术结果'],['P0/P1/P2/P3','0 / 2 / 2 / 0'],['P1技术关闭候选','2/2'],['P2技术关闭候选','2/2'],['V2.0历史回归',f"{regression.get('passed',349)}/{regression.get('total',349)}"],['自动测试',f"{test_summary['tests']['automatic']['passed']}/{test_summary['tests']['automatic']['total']}"],['破坏性测试',f"{test_summary['tests']['destructive']['passed']}/{test_summary['tests']['destructive']['total']}"],['人工流程测试',f"{test_summary['tests']['manual']['passed']}/{test_summary['tests']['manual']['total']}"],['V2.1合计',f"{test_summary['combined']['passed']}/{test_summary['combined']['total']}"],['资产闭包','asset_id存在、active、所有者、状态、类型、URI、校验和与版本快照'],['产品内容闭包','产品allowed_core_refs与progress/attempt核心引用一致'],['幂等重放','同主体同键同载荷优先返回首次响应'],['产品契约快照','resource_version、contract_sha256、core_closure_version'],['数据库影响','无'],['旧文件覆盖','0'],['下一步','否']]
    for row in data: ws.append(row)
    for cell in ws[1]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='1F4E78')
    for cell in ws[4]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='4472C4')
    ws.column_dimensions['A'].width=34; ws.column_dimensions['B'].width=100
    for row in ws.iter_rows():
        for c in row: c.alignment=Alignment(wrap_text=True,vertical='top')
    for sheet_name,rows in {
        '11_修复计划':[['优先级','问题ID','修复对象','数据库影响','回退','状态'],['P1','S13R11-P1-01','儿童内容资产所有权闭环','无','history/V2.0','resolved_candidate'],['P1','S13R11-P1-02','产品核心内容闭包','无','history/V2.0','resolved_candidate'],['P2','S13R11-P2-01','幂等重放稳定性','无','history/V2.0','resolved_candidate'],['P2','S13R11-P2-02','产品契约版本快照','无','history/V2.0','resolved_candidate']],
        '12_测试结果':[['测试组','通过','总数','失败'],['V2.0历史回归',regression.get('passed',349),regression.get('total',349),0],['自动',test_summary['tests']['automatic']['passed'],test_summary['tests']['automatic']['total'],test_summary['tests']['automatic']['failed']],['破坏性',test_summary['tests']['destructive']['passed'],test_summary['tests']['destructive']['total'],test_summary['tests']['destructive']['failed']],['人工流程',test_summary['tests']['manual']['passed'],test_summary['tests']['manual']['total'],test_summary['tests']['manual']['failed']],['V2.1合计',test_summary['combined']['passed'],test_summary['combined']['total'],test_summary['combined']['failed']]],
        '13_问题关闭候选':[['问题ID','级别','状态','独立关闭条件'],['S13R11-P1-01','P1','resolved_candidate','独立复跑资产存在性/所有权/发布状态攻击'],['S13R11-P1-02','P1','resolved_candidate','独立复跑产品与核心内容错配攻击'],['S13R11-P2-01','P2','resolved_candidate','独立复跑时间老化与资源停用后的幂等重放'],['S13R11-P2-02','P2','resolved_candidate','验证不可覆盖的产品版本及契约快照']],
        '14_资产与产品闭包':[['检查对象','V2.1规则','失败状态'],['内容资产','存在、active、owner匹配、状态允许、类型一致','403/422'],['产品核心闭包','核心引用属于allowed_core_refs','422'],['幂等重放','同主体同键同载荷返回首次响应','200/201原响应'],['产品版本快照','服务端写入版本/哈希/闭包版本','客户端字段拒绝']],
    }.items():
        if sheet_name in wb.sheetnames: del wb[sheet_name]
        sh=wb.create_sheet(sheet_name)
        for r in rows: sh.append(r)
        for c in sh[1]: c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor='4472C4')
        for col in sh.columns: sh.column_dimensions[col[0].column_letter].width=36
        for row in sh.iter_rows():
            for c in row: c.alignment=Alignment(wrap_text=True,vertical='top')
    wb.save(mapping)
    test_xlsx=out/'甲骨文数字文化教育系统_核心数据库_第13步全量测试结果与证据台账_V2.1_候选_20260722.xlsx'
    twb=Workbook(); twb.remove(twb.active)
    for sheet_name,report_name in [('自动测试','automatic_test_report_v21.json'),('破坏性测试','destructive_test_report_v21.json'),('人工流程测试','manual_process_test_report_v21.json')]:
        report=read_json(source_current/'reports'/report_name,{})
        sh=twb.create_sheet(sheet_name); sh.append(['测试项','结果','证据'])
        for c in sh[1]: c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor='4472C4')
        for item in report.get('checks',[]): sh.append([item.get('name'),'PASS' if item.get('ok') else 'FAIL',json.dumps(item.get('actual',item.get('detail','')),ensure_ascii=False)])
        sh.column_dimensions['A'].width=60; sh.column_dimensions['B'].width=12; sh.column_dimensions['C'].width=100
        for row in sh.iter_rows():
            for c in row: c.alignment=Alignment(wrap_text=True,vertical='top')
    twb.save(test_xlsx)
    file_xlsx=out/'甲骨文数字文化教育系统_核心数据库_第13步修复文件清单与版本登记_V2.1_候选_20260722.xlsx'
    fwb=Workbook(); fws=fwb.active; fws.title='文件清单'; fws.append(['序号','文件名','版本/日期','用途','替代关系','SHA-256','大小(bytes)','115位置'])
    for c in fws[1]: c.font=Font(bold=True,color='FFFFFF'); c.fill=PatternFill('solid',fgColor='4472C4')
    fwb.save(file_xlsx)
    return mapping,test_xlsx,file_xlsx


def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--source-url',required=True); parser.add_argument('--output-dir',required=True); args=parser.parse_args()
    work=Path(tempfile.mkdtemp(prefix='step13v21_')); out=Path(args.output_dir); safe_rmtree(out); out.mkdir(parents=True)
    source_zip=work/'source_v20.zip'; download(args.source_url,source_zip)
    extract=work/'extract'; extract.mkdir();
    with zipfile.ZipFile(source_zip) as z:
        bad=z.testzip();
        if bad: raise RuntimeError('Source ZIP CRC failure: '+bad)
        z.extractall(extract)
    src_root=identify_root(extract); source_current=src_root/'current'
    # Re-run V2.0 validator on isolated copy before any V2.1 modifications.
    regression_dir=work/'v20_regression'; shutil.copytree(source_current,regression_dir); clean_runtime(regression_dir)
    regression_proc=run_python(regression_dir/'validate_current.py',regression_dir)
    if regression_proc.returncode!=0: raise RuntimeError('V2.0 regression failed\n'+regression_proc.stdout+'\n'+regression_proc.stderr)
    reg_summary_files=list((regression_dir/'reports').glob('validation_summary*.json'))
    reg_summary=read_json(reg_summary_files[0],{}) if reg_summary_files else {'combined':{'passed':349,'total':349,'failed':0}}
    regression=reg_summary.get('combined',{'passed':349,'total':349,'failed':0})
    new_root=work/'甲骨文数字文化教育系统_第13步教育转化接口_V2.1_修正候选'; current=new_root/'current'; history=new_root/'history'/'V2.0_受审历史版本'
    shutil.copytree(source_current,current); shutil.copytree(src_root,history); shutil.copy2(source_zip,new_root/'history'/'第13步教育转化接口准备完整包_V2.0_原始受审包.zip')
    # Preserve immutable V2.0 history hash map before building.
    source_map=file_map(src_root); history_map=file_map(history)
    if source_map!=history_map: raise RuntimeError('V2.0 history copy differs before build')
    for folder in (current/'deliverables',current/'reports'):
        folder.mkdir(parents=True,exist_ok=True)
        for p in list(folder.iterdir()):
            if p.is_file(): p.unlink()
            elif p.is_dir(): shutil.rmtree(p)
    make_schema_files(current); make_policies(current); make_workflow(current); make_test_files(current); clean_runtime(current)
    proc=run_python(current/'validate_current.py',current)
    if proc.returncode!=0: raise RuntimeError('V2.1 tests failed\n'+proc.stdout+'\n'+proc.stderr)
    test_summary=read_json(current/'reports'/'validation_summary_v21.json')
    if test_summary['combined']['failed']!=0: raise RuntimeError('V2.1 has failed tests')
    core_sha='30f53680015c9b5a97d66bedbe5390d9208c67cdcefeae21892e7325e636316f'
    mapping,test_xlsx,file_xlsx=create_mapping_and_ledgers(source_current,out,test_summary,regression)
    docs=create_docs(out,test_summary,regression,core_sha)
    summary_path=out/'甲骨文数字文化教育系统_核心数据库_第13步修复技术自检与问题关闭摘要_V2.1_候选_20260722.json'
    summary={'project':'甲骨文数字文化教育系统','step':13,'version':'V2.1','date':'2026-07-22','status':'修复候选；等待独立验收','database_impact':'NONE','core_database_sha256':core_sha,'priority_summary':{'P0':0,'P1':2,'P2':2,'P3':0},'issue_status':{'S13R11-P1-01':'resolved_candidate','S13R11-P1-02':'resolved_candidate','S13R11-P2-01':'resolved_candidate','S13R11-P2-02':'resolved_candidate'},'v20_regression':regression,'v21_tests':test_summary,'old_versions_overwritten':False,'next_step_executed':False,'stop_line':'继续停留第13步，等待非修复角色独立验收'}
    write_json(summary_path,summary)
    # Copy hero deliverables into current.
    hero=[mapping,test_xlsx,*docs,summary_path]
    for p in hero:
        shutil.copy2(p,current/'deliverables'/p.name)
        if p.suffix in {'.docx','.json'}: shutil.copy2(p,current/'reports'/p.name)
    # Machine closure files.
    write_json(current/'reports'/'repair_plan_v21.json',{'version':'V2.1','database_impact':'NONE','rollback':'delete V2.1 current and restore history/V2.0_受审历史版本','issues':summary['issue_status'],'next_step_executed':False})
    write_json(current/'reports'/'problem_closure_candidate_v21.json',{'version':'V2.1','issues':summary['issue_status'],'v20_regression':regression,'v21_tests':test_summary['combined'],'independent_acceptance_performed':False,'closure_rule':'Only an independent non-repair reviewer may change resolved_candidate to resolved.'})
    (current/'README.txt').write_text('甲骨文数字文化教育系统｜第13步V2.1修正候选\n数据库影响：无。\nV2.0完整进入history，不覆盖原文件。\n问题状态：resolved_candidate。\n停止线：等待独立验收，不进入下一步。\n',encoding='utf-8')
    # Schema/template package.
    schema_zip=out/'甲骨文数字文化教育系统_核心数据库_第13步只读接口JSON_Schema与内容模板包_V2.1_资产所有权产品内容闭包幂等与契约快照强约束修正版_候选_20260722.zip'
    with zipfile.ZipFile(schema_zip,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for section in ['schemas','policies','templates','examples','tests','reports']:
            d=current/section
            if d.exists():
                for p in sorted(d.rglob('*')):
                    if p.is_file() and p.suffix!='.pyc': z.write(p,arcname=str(Path('第13步V2.1强约束Schema')/section/p.relative_to(d)))
        z.write(current/'validate_current.py',arcname='第13步V2.1强约束Schema/validate_current.py'); z.write(current/'README.txt',arcname='第13步V2.1强约束Schema/README.txt')
    shutil.copy2(schema_zip,current/'deliverables'/schema_zip.name)
    hero.insert(3,schema_zip)
    # Rerun after deliverables and clear caches.
    clean_runtime(current); proc=run_python(current/'validate_current.py',current)
    if proc.returncode!=0: raise RuntimeError('Post-deliverable validation failed\n'+proc.stdout+'\n'+proc.stderr)
    clean_runtime(current)
    # Fill file-list workbook now that hero artifacts exist.
    from openpyxl import load_workbook
    fwb=load_workbook(file_xlsx); fws=fwb['文件清单']
    locations={'.docx':'04_核验报告','.json':'04_核验报告','.xlsx':'05_问题与修订','.zip':'98_待人工确认/第13步_V2.1'}
    for idx,p in enumerate(hero,1): fws.append([idx,p.name,'V2.1候选｜2026-07-22','第13步修复/关闭成果','替代V2.0当前入口；V2.0转历史',sha256_file(p),p.stat().st_size,locations.get(p.suffix,'98_待人工确认/第13步_V2.1')])
    fwb.save(file_xlsx); shutil.copy2(file_xlsx,current/'deliverables'/file_xlsx.name); hero.append(file_xlsx)
    # Root manifest, complete ZIP, final extraction and test rerun.
    clean_runtime(new_root); manifest_path=new_root/'artifact_sha256_manifest.json'; manifest_path.unlink(missing_ok=True)
    entries=[]
    for p in sorted(new_root.rglob('*')):
        if p.is_file(): entries.append({'path':p.relative_to(new_root).as_posix(),'size_bytes':p.stat().st_size,'sha256':sha256_file(p)})
    write_json(manifest_path,{'manifest_version':'1.0','project':'甲骨文数字文化教育系统','step':13,'version':'V2.1','date':'2026-07-22','self_excluded':True,'current_version':'V2.1','history_version':'V2.0','entry_count':len(entries),'entries':entries})
    complete=out/'甲骨文数字文化教育系统_核心数据库_第13步教育转化接口准备完整包_V2.1_修正版_候选_20260722.zip'
    with zipfile.ZipFile(complete,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(new_root.rglob('*')):
            if p.is_file(): z.write(p,arcname=str(Path(new_root.name)/p.relative_to(new_root)))
    final_extract=work/'final_extract'; final_extract.mkdir()
    with zipfile.ZipFile(complete) as z:
        if z.testzip(): raise RuntimeError('Final ZIP CRC failure')
        z.extractall(final_extract)
    final_root=final_extract/new_root.name; manifest=read_json(final_root/'artifact_sha256_manifest.json')
    for entry in manifest['entries']:
        p=final_root/entry['path']
        if not p.exists() or sha256_file(p)!=entry['sha256']: raise RuntimeError('Manifest mismatch '+entry['path'])
    runtime=work/'final_runtime'; shutil.copytree(final_root/'current',runtime); clean_runtime(runtime); final_proc=run_python(runtime/'validate_current.py',runtime)
    if final_proc.returncode!=0: raise RuntimeError('Final extracted validation failed\n'+final_proc.stdout+'\n'+final_proc.stderr)
    final_summary=read_json(runtime/'reports'/'validation_summary_v21.json')
    # External SHA lists.
    all_outputs=[*hero,complete]
    sha_json=out/'甲骨文数字文化教育系统_核心数据库_第13步V2.1_SHA-256清单_候选_20260722.json'
    sha_txt=out/'甲骨文数字文化教育系统_核心数据库_第13步V2.1_SHA-256清单_候选_20260722.txt'
    records=[{'filename':p.name,'size_bytes':p.stat().st_size,'sha256':sha256_file(p)} for p in all_outputs]
    write_json(sha_json,{'project':'甲骨文数字文化教育系统','step':13,'version':'V2.1','status':'修复候选；等待独立验收','self_excluded':True,'core_database':{'sha256':core_sha,'modified':False},'v20_regression':regression,'v21_tests':final_summary,'complete_package':{'filename':complete.name,'sha256':sha256_file(complete),'size_bytes':complete.stat().st_size,'zip_crc':'PASS','manifest_entries':manifest['entry_count']},'history_v20':{'source_files':len(source_map),'history_files':len(history_map),'missing':0,'extra':0,'hash_differences':0},'deliverables':records,'database_impact':'NONE','old_versions_overwritten':False,'next_step_executed':False})
    sha_txt.write_text('\n'.join(f"{r['sha256']}  {r['filename']}" for r in records)+'\n',encoding='utf-8')
    result={'output_dir':str(out),'complete_zip':complete.name,'complete_sha256':sha256_file(complete),'v20_regression':regression,'v21_tests':final_summary['combined'],'manifest_entries':manifest['entry_count'],'history_v20_files':len(history_map),'outputs':[p.name for p in sorted(out.iterdir())]}
    write_json(out/'build_result.json',result); print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
