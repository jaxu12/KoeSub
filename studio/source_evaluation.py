"""Offline source-quality studies, separate from production inference and projects.

Character differences are automatic diagnostics. Semantic error counts require
explicit user-attested listening and an audio-audited reference, never an LLM vote.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os

from .core import atomic_text,now,read_json_file,uid
from .evaluation_text import normalize_text,score_text
from .pipeline import digest

VARIANTS=('baseline','review')
CATEGORIES={
    'omission':'Spoken content is missing, beyond subtitle compression or spelling.',
    'addition':'The hypothesis contains content that was not spoken.',
    'name':'A person, place, title or other named entity is wrong.',
    'meaning':'Other wording changes a fact, negation, intent or relationship.',
    'orthography':'Spelling or script differs while meaning is preserved.',
    'timing':'Cue timing is wrong despite otherwise usable text.'}
SEVERITIES=('minor','major','critical')


def audio_hash(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def check_audio(case):
    path=Path(case['audio']['path'])
    if not path.is_file() or audio_hash(path)!=case['audio']['sha256']:
        raise ValueError('Missing or changed study audio; listening cannot be attested.')
    return path


def reference_key(case):
    return digest([case['audio'],case['reference']])


def rating_key(case,variant):
    return digest([reference_key(case),case['variants'][variant]])


def source_key(case):
    return digest({k:case[k] for k in ('id','audio','published_reference','source','variants')})


def _completed_stage(state,manifest,key):
    stage=next((s for s in state['stages'] if s['id']==key),None)
    if not stage or stage['status']!='completed':
        return {'available':False,'error':'Stage unavailable: '+key}
    path=Path(stage.get('artifact',Path(manifest).parent/key/'result.json'))
    value=read_json_file(path)
    if digest(value)!=stage.get('digest'):raise ValueError('Changed evaluation source artifact: '+key)
    cues=value.get('track',{}).get('segments',[]);config=state['config']
    if (not cues or any(type(s.get('start')) is not int or type(s.get('end')) is not int
        or not 0<=s['start']<s['end']<=config['duration'] or not isinstance(s.get('text'),str) or not s['text'].strip() for s in cues)):
        raise ValueError('Invalid transcript evidence for evaluation: '+key)
    return {'available':True,'text':'\n'.join(s['text'] for s in cues),
        'cues':[{k:s[k] for k in ('id','start','end','text')} for s in cues],
        'evidence':{'manifest':str(manifest),'stage':key,'artifact':str(path),'digest':stage['digest']}}


def create_study(index_path,results_path):
    index=read_json_file(index_path);collection=read_json_file(results_path)
    samples=index['samples'];records=collection['records']
    if not 1<=len(samples)<=1000:raise ValueError('A study requires 1–1000 prepared clips.')
    if len({s['id'] for s in samples})!=len(samples) or len({r['id'] for r in records})!=len(records):
        raise ValueError('Duplicate study sample IDs.')
    by_id={r['id']:r for r in records}
    if not set(by_id).issubset({s['id'] for s in samples}):raise ValueError('Result IDs do not match the reference index.')
    cases=[]
    for sample in samples:
        start,end=sample['source_range_ms'];duration=end-start
        if not 0<duration<=600000:raise ValueError('Use complete prepared clips up to ten minutes each.')
        case={'id':sample['id'],'audio':{'path':str(Path(sample['audio']).resolve()),'sha256':sample['audio_sha256'],'duration_ms':duration},
            'published_reference':sample['reference_jp'],'reference':sample['reference_jp'],
            'source':{'index':str(Path(index_path).resolve()),'source_range_ms':[start,end],
                'results':str(Path(results_path).resolve()),
                'dataset':index.get('dataset',''),'revision':index.get('revision',''),
                'source_group':sample.get('source_group','unspecified'),
                'reference_status':sample.get('reference_status','Published caption; not audited in this study')},
            'reference_audit':None,'ratings':{},'history':[]}
        check_audio(case)
        case['variants']={v:{'available':False,'error':'No completed run supplied for this clip'} for v in VARIANTS}
        if sample['id'] in by_id:
            manifest=Path(by_id[sample['id']]['manifest']).resolve();state=read_json_file(manifest)
            config=state['config']
            if (state.get('version')!=1 or digest({'config':config,'assets':state['assets']})!=state['fingerprint']):
                raise ValueError('Changed source manifest configuration.')
            if (Path(config['media']).resolve()!=Path(case['audio']['path']) or config['start']!=0
                or config['duration']!=duration):raise ValueError('Study and run must cover the same complete prepared audio clip.')
            case['variants']={v:_completed_stage(state,manifest,key) for v,key in [('baseline','asr-0'),('review','jp-layout')]}
        case['source_digest']=source_key(case);cases.append(case)
    study={'version':1,'id':uid(),'created':now(),'updated':now(),'cases':cases,
        'scope':'Post-inference evaluation only; imported reference text is never sent to production models.',
        'source_assets':'Frozen completed results; model weights and runtimes need not remain installed.'}
    validate_study(study)
    return study


def _reviewer(value):
    if not isinstance(value,str) or not value.strip() or len(value)>100:raise ValueError('Enter a reviewer name or ID.')
    return value.strip()


def audit_reference(case,text,reviewer,note,*,listened=False):
    reviewer=_reviewer(reviewer)
    if type(listened) is not bool:raise ValueError('Listening attestation must be explicit.')
    if not isinstance(text,str) or not text.strip() or len(text)>20000 or not normalize_text(text):raise ValueError('Enter non-empty reference text.')
    if not isinstance(note,str) or not note.strip() or len(note)>2000:raise ValueError('Describe the reference check or correction.')
    if listened:check_audio(case)
    if text!=case['reference']:
        case['history'].append({'at':now(),'reviewer':reviewer,'reason':'Reference corrected; prior ratings invalidated',
            'reference':case['reference'],'reference_audit':case['reference_audit'],'ratings':deepcopy(case['ratings'])})
        case['reference']=text;case['ratings']={}
    elif case['reference_audit']:
        case['history'].append({'at':now(),'reason':'Reference audit revised','reference_audit':deepcopy(case['reference_audit'])})
    case['reference_audit']={'listened':bool(listened),'reviewer':reviewer,'note':note.strip(),'at':now(),'source':reference_key(case)}


def validate_event(case,variant,event):
    if event.get('category') not in CATEGORIES or event.get('severity') not in SEVERITIES:raise ValueError('Invalid error category or severity.')
    reference=event.get('reference_quote');hypothesis=event.get('hypothesis_quote');note=event.get('note')
    if not all(isinstance(v,str) and len(v)<=2000 for v in (reference,hypothesis,note)) or not note.strip():
        raise ValueError('Add a brief explanation and exact evidence quotes.')
    if reference and reference not in case['reference']:raise ValueError('Reference quote is not present in this case.')
    if hypothesis and hypothesis not in case['variants'][variant]['text']:raise ValueError('Hypothesis quote is not present in this variant.')
    category=event['category']
    if not reference and not hypothesis:raise ValueError('At least one evidence quote is required.')
    if category=='omission' and not reference:raise ValueError('Omission requires a reference quote.')
    if category=='addition' and not hypothesis:raise ValueError('Addition requires a hypothesis quote.')
    if category in ('name','meaning','orthography') and (not reference or not hypothesis):raise ValueError('This category requires both evidence quotes.')


def record_rating(case,variant,events,reviewer,*,listened=False):
    reviewer=_reviewer(reviewer)
    if variant not in VARIANTS or not case['variants'][variant]['available']:raise ValueError('No usable hypothesis for this variant.')
    if type(listened) is not bool or len(events)>2000:raise ValueError('Invalid listening attestation or event count.')
    if listened:check_audio(case)
    events=deepcopy(events)
    for event in events:
        validate_event(case,variant,event);event.setdefault('id',uid())
    if len({e['id'] for e in events})!=len(events):raise ValueError('Duplicate error event IDs.')
    if variant in case['ratings']:
        case['history'].append({'at':now(),'reason':'Variant rating revised','variant':variant,'rating':deepcopy(case['ratings'][variant])})
    case['ratings'][variant]={'listened':listened,'reviewer':reviewer,'at':now(),'events':events,'source':rating_key(case,variant)}


def validate_study(study):
    if study.get('version')!=1 or not isinstance(study.get('cases'),list) or not 1<=len(study['cases'])<=1000:
        raise ValueError('Unsupported or empty quality study.')
    if len({c['id'] for c in study['cases']})!=len(study['cases']):raise ValueError('Duplicate case IDs.')
    for case in study['cases']:
        if case.get('source_digest')!=source_key(case):raise ValueError('Changed frozen study source.')
        if not isinstance(case['reference'],str) or not normalize_text(case['reference']) or len(case['reference'])>20000:
            raise ValueError('Invalid reference text.')
        if set(case['variants'])!=set(VARIANTS):raise ValueError('Invalid evaluation variants.')
        audit=case.get('reference_audit')
        if audit:
            if type(audit.get('listened')) is not bool or audit.get('source')!=reference_key(case):raise ValueError('Stale reference listening attestation.')
            _reviewer(audit.get('reviewer'))
            if not isinstance(audit.get('note'),str) or not audit['note'].strip() or len(audit['note'])>2000 or not isinstance(audit.get('at'),str) or not audit['at']:
                raise ValueError('Reference audit needs an explanation and timestamp.')
        if not set(case['ratings']).issubset(VARIANTS):raise ValueError('Invalid variant ratings.')
        for variant,rating in case['ratings'].items():
            if (not case['variants'][variant]['available'] or type(rating.get('listened')) is not bool
                or rating.get('source')!=rating_key(case,variant)):raise ValueError('Stale hypothesis rating.')
            _reviewer(rating.get('reviewer'))
            if not isinstance(rating.get('at'),str) or not rating['at']:raise ValueError('Rating needs a timestamp.')
            for event in rating['events']:validate_event(case,variant,event)
            if len({e['id'] for e in rating['events']})!=len(rating['events']):raise ValueError('Duplicate error event IDs.')


def qualified(case,variant):
    return bool(case.get('reference_audit',{} ) and case['reference_audit']['listened']
                and case['ratings'].get(variant,{}).get('listened'))


def quality_report(study):
    validate_study(study);cases=study['cases'];variants={};paired=[]
    for variant in VARIANTS:
        available=[c for c in cases if c['variants'][variant]['available']]
        scored=[score_text(c['reference'],c['variants'][variant]['text']) for c in available]
        audited=[c for c in available if (c.get('reference_audit') or {}).get('listened')]
        audited_scores=[score_text(c['reference'],c['variants'][variant]['text']) for c in audited]
        human=[c for c in available if qualified(c,variant)]
        events=[e for c in human for e in c['ratings'][variant]['events']]
        errors=sum(s['edit_distance'] for s in scored);chars=sum(s['reference_characters'] for s in scored)
        verified_chars=sum(s['reference_characters'] for s in audited_scores)
        seconds=sum(c['audio']['duration_ms']/1000 for c in human)
        variants[variant]={'available_cases':len(available),'expected_cases':len(cases),
            'automatic_text_difference':{'edit_distance':errors,'reference_characters':chars,
                'substitutions':sum(s['substitutions'] for s in scored),'deletions':sum(s['deletions'] for s in scored),
                'insertions':sum(s['insertions'] for s in scored),'cer_available':errors/chars if chars else None,
                'cer_complete':errors/chars if chars and len(available)==len(cases) else None},
            'audio_audited_reference_cer':{'cases':len(audited),'characters':verified_chars,
                'cer':sum(s['edit_distance'] for s in audited_scores)/verified_chars if verified_chars else None},
            'user_attested_semantic_review':{'cases':len(human),'seconds':seconds,
                'events_by_category':{category:sum(e['category']==category for e in events) if human else None for category in CATEGORIES},
                'events_by_severity':{level:sum(e['severity']==level for e in events) if human else None for level in SEVERITIES},
                'semantic_events':sum(e['category'] in ('omission','addition','name','meaning') for e in events) if human else None,
                'clean_cases':sum(not c['ratings'][variant]['events'] for c in human) if human else None}}
    paired_cases=[c for c in cases if all(qualified(c,v) for v in VARIANTS)]
    for case in paired_cases:
        counts={v:sum(e['category'] in ('omission','addition','name','meaning') for e in case['ratings'][v]['events']) for v in VARIANTS}
        paired.append({'id':case['id'],**counts,'effect':'improved' if counts['review']<counts['baseline'] else 'worsened' if counts['review']>counts['baseline'] else 'unchanged'})
    rows=[]
    for case in cases:
        rows.append({'id':case['id'],'reference_audio_audited':bool((case.get('reference_audit') or {}).get('listened')),
            'reference_changed':case['reference']!=case['published_reference'],
            'audio':deepcopy(case['audio']),'reference':case['reference'],'published_reference':case['published_reference'],
            'source':deepcopy(case['source']),'reference_audit':deepcopy(case['reference_audit']),
            'variants':{v:{'available':case['variants'][v]['available'],'semantic_review_complete':qualified(case,v),
                'snapshot':deepcopy(case['variants'][v]),'rating':deepcopy(case['ratings'].get(v)),
                'automatic_text_difference':score_text(case['reference'],case['variants'][v]['text']) if case['variants'][v]['available'] else None,
                'cer':score_text(case['reference'],case['variants'][v]['text'])['cer'] if case['variants'][v]['available'] else None} for v in VARIANTS}})
    return {'version':1,'study':study['id'],'created':now(),'variants':variants,'cases':rows,
        'paired_semantic_comparison':{'cases':len(paired),'results':paired,
            'events_by_category':{v:{category:sum(e['category']==category for c in paired_cases for e in c['ratings'][v]['events']) if paired_cases else None for category in CATEGORIES} for v in VARIANTS},
            'basis':'Primary semantic event counts only; not a severity-weighted or automatic meaning verdict',
            **{effect:sum(p['effect']==effect for p in paired) if paired else None for effect in ('improved','worsened','unchanged')}},
        'limitations':['Character deletions/insertions are text edits, not confirmed omissions/additions.',
            'Semantic categories require user-attested listening and an audio-audited reference; null means no qualified ratings.',
            'Paired comparisons use only cases completed for both variants. Availability and listening coverage are reported separately.',
            'Event counts are primary human categories, not automatic word-error counts or a guarantee of independent reviewers.',
            'Evaluation never changes production subtitles or supplies references to inference.'],
        'inference_performed':False,'source_groups':sorted({c['source'].get('source_group','unspecified') for c in cases})}


def report_markdown(report):
    rows=['# KoeSub source-quality evaluation','',
        'Text differences and user-attested audio review are reported separately. Missing audit coverage is not zero errors.','',
        '| Measure | Baseline | After review |','|---|---:|---:|']
    variants=report['variants']
    def value(variant,key):
        data=variants[variant]
        if key=='coverage':return f'{data["available_cases"]}/{data["expected_cases"]}'
        if key=='cer':return f'{data["automatic_text_difference"]["cer_available"]:.2%}' if data['automatic_text_difference']['cer_available'] is not None else 'N/A'
        if key=='listened':return str(data['user_attested_semantic_review']['cases'])
        if key=='audited_cer':
            metric=data['audio_audited_reference_cer']['cer'];return f'{metric:.2%}' if metric is not None else 'Not assessed'
        val=report['paired_semantic_comparison']['events_by_category'][variant][key]
        return str(val) if val is not None else 'Not assessed'
    for title,key in [('Available clips','coverage'),('CER over available text','cer'),('CER on audio-audited references','audited_cer'),('Clips with audited reference and completed listening review','listened')]+[('Paired '+k+' events',k) for k in CATEGORIES]:
        rows.append(f'| {title} | {value("baseline",key)} | {value("review",key)} |')
    rows+=['',f'Paired semantic comparison: {report["paired_semantic_comparison"]["cases"]} fully reviewed clips.','']
    rows += ['- '+item for item in report['limitations']]
    return '\n'.join(rows)+'\n'


def write_reports(study,path,study_path=None):
    path=Path(path);protected={Path(study_path).resolve()} if study_path else set();run_roots=set()
    for case in study['cases']:
        protected.update((Path(case['audio']['path']).resolve(),Path(case['source']['index']).resolve()))
        if case['source'].get('results'):protected.add(Path(case['source']['results']).resolve())
        for value in case['variants'].values():
            if value['available']:
                protected.update(Path(value['evidence'][key]).resolve() for key in ('manifest','artifact'))
                run_roots.add(Path(value['evidence']['manifest']).resolve().parent)
    if (path.suffix.lower()!='.json' or path.resolve() in protected or path.with_suffix('.md').resolve() in protected
        or any(path.resolve().is_relative_to(root) for root in run_roots)):
        raise ValueError('Choose a separate JSON report path; study and source evidence are protected.')
    report=quality_report(study);atomic_text(path,json.dumps(report,ensure_ascii=False,indent=2))
    atomic_text(path.with_suffix('.md'),report_markdown(report));return report


@contextmanager
def _save_lock(path):
    with path.with_suffix(path.suffix+'.lock').open('a+b') as lock:
        lock.seek(0,2)
        if not lock.tell():lock.write(b'0');lock.flush()
        lock.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:raise ValueError('Another editor is saving this study.') from exc
        try:yield
        finally:
            if os.name=='nt':msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


class StudyStore:
    def __init__(self,path):self.path=Path(path);self.token=None

    def load(self):
        value=read_json_file(self.path);validate_study(value);self.token=digest(value);return value

    def save(self,study):
        validate_study(study);self.path.parent.mkdir(parents=True,exist_ok=True)
        with _save_lock(self.path):
            actual=digest(read_json_file(self.path)) if self.path.exists() else None
            if actual!=self.token:raise ValueError('Study changed in another editor. Reopen it before saving.')
            study['updated']=now()
            atomic_text(self.path,json.dumps(study,ensure_ascii=False,indent=2));self.token=digest(study)
