from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from studio.core import Segment,Track,atomic_text
from studio.pipeline import digest
from studio.source_evaluation import (StudyStore,audio_hash,create_study,audit_reference,record_rating,
    quality_report,report_markdown,validate_study,write_reports)


@pytest.fixture
def study_files(tmp_path):
    import json
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);atomic_text(path,json.dumps(value,ensure_ascii=False))
    samples=[];records=[]
    for i,text in enumerate(('田中さんは京都へ行きません。','魚が好きです。')):
        audio=tmp_path/f'clip-{i}.wav';audio.write_bytes(b'synthetic local audio '+bytes([i]))
        samples.append({'id':f'clip-{i}','audio':str(audio),'audio_sha256':audio_hash(audio),
            'source_range_ms':[10000*i,10000*i+3000],'reference_jp':text,'human_audio_verified':True})
        if i:continue
        config={'media':str(audio),'start':0,'duration':3000}
        state={'version':1,'config':config,'assets':[{'path':'missing-model.bin'}],'stages':[]}
        state['fingerprint']=digest({'config':config,'assets':state['assets']})
        manifest=tmp_path/'run/manifest.json'
        for key,hyp in [('asr-0','山田さんは東京へ行きます。'),('jp-layout',text)]:
            value={'track':asdict(Track('fixture',[Segment(0,3000,hyp)]))}
            path=manifest.parent/key/'result.json';write(path,value)
            state['stages'].append({'id':key,'status':'completed','artifact':str(path),'digest':digest(value)})
        write(manifest,state);records.append({'id':f'clip-{i}','manifest':str(manifest)})
    index=tmp_path/'index.json';collection=tmp_path/'results.json'
    write(index,{'samples':samples});write(collection,{'records':records})
    return index,collection,create_study(index,collection)


def event(category='name'):
    return {'category':category,'severity':'major','reference_quote':'田中','hypothesis_quote':'山田','note':'Synthetic example: different person.'}


def test_unverified_labels_and_missing_runs_cannot_become_zero_semantic_errors(study_files):
    _,_,study=study_files;report=quality_report(study)
    base=report['variants']['baseline']
    assert base['available_cases']==1 and base['expected_cases']==2
    assert base['automatic_text_difference']['cer_available']>0
    assert base['automatic_text_difference']['cer_complete'] is None
    assert base['audio_audited_reference_cer']['cer'] is None
    assert all(v is None for v in base['user_attested_semantic_review']['events_by_category'].values())
    assert report['paired_semantic_comparison']['improved'] is None
    assert 'Not assessed' in report_markdown(report)
    # An upstream dataset's human_audio_verified flag is deliberately not an
    # attestation by a reviewer in this study.
    assert all(c['reference_audit'] is None for c in study['cases'])


def test_listening_coverage_and_clean_cases_require_both_reference_and_variant_attestations(study_files):
    case=study_files[2]['cases'][0]
    record_rating(case,'baseline',[event()],'synthetic-test',listened=True)
    assert quality_report(study_files[2])['variants']['baseline']['user_attested_semantic_review']['cases']==0
    audit_reference(case,case['reference'],'synthetic-test','Synthetic listening attestation',listened=True)
    report=quality_report(study_files[2]);assert report['variants']['baseline']['user_attested_semantic_review']['events_by_category']['name']==1
    assert report['paired_semantic_comparison']['cases']==0
    record_rating(case,'review',[],'synthetic-test',listened=False)
    assert quality_report(study_files[2])['paired_semantic_comparison']['cases']==0
    record_rating(case,'review',[],'synthetic-test',listened=True)
    report=quality_report(study_files[2]);assert report['paired_semantic_comparison']['improved']==1
    assert report['variants']['review']['user_attested_semantic_review']['clean_cases']==1
    assert report['variants']['review']['user_attested_semantic_review']['semantic_events']==0


def test_character_edits_and_orthography_are_not_automatically_meaning_errors(study_files):
    study=study_files[2];case=study['cases'][0]
    audit_reference(case,case['reference'],'synthetic-test','Fixture',listened=True)
    record_rating(case,'baseline',[event('orthography')],'synthetic-test',listened=True)
    report=quality_report(study);base=report['variants']['baseline']
    assert base['automatic_text_difference']['edit_distance']>0
    assert base['user_attested_semantic_review']['events_by_category']['orthography']==1
    assert base['user_attested_semantic_review']['semantic_events']==0


def test_reference_correction_invalidates_ratings_and_retains_originals_and_history(study_files):
    study=study_files[2];case=study['cases'][0];original=deepcopy(case['variants'])
    audit_reference(case,case['reference'],'synthetic-test','Fixture audit',listened=True)
    record_rating(case,'baseline',[event()],'synthetic-test',listened=True)
    audit_reference(case,'田中さんは京都に行きません。','synthetic-test','Corrected a particle',listened=False)
    assert not case['ratings'] and not case['reference_audit']['listened']
    assert case['published_reference']=='田中さんは京都へ行きません。'
    assert case['history'][-1]['ratings']['baseline']['events'][0]['category']=='name'
    assert case['variants']==original
    assert quality_report(study)['variants']['baseline']['user_attested_semantic_review']['cases']==0


@pytest.mark.parametrize('tamper',['reference','hypothesis','audit','event','rating'])
def test_changed_sources_or_stale_labels_are_rejected(study_files,tamper):
    study=study_files[2];case=study['cases'][0]
    audit_reference(case,case['reference'],'synthetic-test','Fixture',listened=True)
    record_rating(case,'baseline',[event()],'synthetic-test',listened=True)
    if tamper=='reference':case['reference']+='変更'
    if tamper=='hypothesis':case['variants']['baseline']['text']+='変更'
    if tamper=='audit':case['reference_audit']['source']='wrong'
    if tamper=='event':case['ratings']['baseline']['events'][0]['hypothesis_quote']='存在しない'
    if tamper=='rating':case['ratings']['baseline']['source']='wrong'
    with pytest.raises(ValueError):validate_study(study)


def test_audio_change_cannot_be_attested_and_does_not_mutate_reference(study_files):
    case=study_files[2]['cases'][0];before=deepcopy(case)
    Path(case['audio']['path']).write_bytes(b'different audio')
    with pytest.raises(ValueError,match='audio'):audit_reference(case,'別の文章','synthetic-test','Fixture',listened=True)
    assert case==before
    with pytest.raises(ValueError,match='explicit'):audit_reference(case,case['reference'],'synthetic-test','Fixture',listened='false')


@pytest.mark.parametrize('change',[{'category':'unknown'},{'severity':'unknown'},{'reference_quote':'missing'},
    {'hypothesis_quote':'missing'},{'note':''},{'reference_quote':'','hypothesis_quote':''}])
def test_error_events_need_valid_category_severity_and_actual_evidence(study_files,change):
    case=study_files[2]['cases'][0]
    with pytest.raises(ValueError):record_rating(case,'baseline',[event()|change],'synthetic-test',listened=False)
    assert not case['ratings']


def test_concurrent_study_save_refuses_to_overwrite_another_reviewers_work(study_files,tmp_path):
    study=study_files[2];first=StudyStore(tmp_path/'study.json');first.save(study)
    second=StudyStore(first.path);other=second.load()
    audit_reference(other['cases'][0],other['cases'][0]['reference'],'reviewer-2','Second reviewer draft',listened=False)
    second.save(other)
    with pytest.raises(ValueError,match='another editor'):first.save(study)
    assert StudyStore(first.path).load()['cases'][0]['reference_audit']['reviewer']=='reviewer-2'


def test_reports_do_not_overwrite_study_or_production_evidence(study_files,tmp_path):
    index,_,study=study_files;path=tmp_path/'study.json';StudyStore(path).save(study)
    evidence=Path(study['cases'][0]['variants']['baseline']['evidence']['artifact']);before=evidence.read_bytes()
    for output in (index,path,evidence):
        with pytest.raises(ValueError,match='protected'):write_reports(study,output,path)
    result=write_reports(study,tmp_path/'report.json',path)
    assert (tmp_path/'report.md').is_file() and evidence.read_bytes()==before
    assert result['variants']['baseline']['expected_cases']==2


def test_changed_completed_stage_and_audio_ranges_cannot_enter_comparison(study_files):
    import json
    index,collection,study=study_files
    artifact=Path(study['cases'][0]['variants']['review']['evidence']['artifact'])
    value=json.loads(artifact.read_text(encoding='utf8'));value['track']['segments'][0]['text']='changed'
    artifact.write_text(json.dumps(value),encoding='utf8')
    with pytest.raises(ValueError,match='artifact'):create_study(index,collection)


def test_paired_categories_exclude_unmatched_listening_coverage(study_files):
    from studio.source_evaluation import source_key
    study=study_files[2];case=study['cases'][0]
    audit_reference(case,case['reference'],'synthetic-test','Fixture',listened=True)
    record_rating(case,'baseline',[event()],'synthetic-test',listened=True)
    record_rating(case,'review',[],'synthetic-test',listened=True)
    extra=deepcopy(case);extra['id']='unmatched';extra['ratings']={};extra['source_digest']=source_key(extra)
    record_rating(extra,'baseline',[event('addition')|{'reference_quote':''}],'synthetic-test',listened=True)
    study['cases'].append(extra);report=quality_report(study)
    assert report['variants']['baseline']['user_attested_semantic_review']['events_by_category']['addition']==1
    paired=report['paired_semantic_comparison']
    assert paired['cases']==1 and paired['events_by_category']['baseline']['addition']==0
    assert paired['events_by_category']['baseline']['name']==1 and paired['improved']==1
