import copy
import sys
from dataclasses import asdict
import pytest

from studio import ai_review
from studio.core import Project,Segment,Track


def result(status='needs_review',suggestion='No.'):
    return {'status':status,'issue_type':'meaning' if status!='ok' else 'none',
            'reason':'Negative response in this context.','suggested_translation':suggestion,
            'requires_audio_review':False}


def project_with_results():
    project=Project();project.add_track(Track('JA',[Segment(0,2000,'いえ。',translation='House.'),
                                                Segment(2500,4500,'すごい！',translation='すごい！')]))
    for i,s in enumerate(project.active.segments):
        project.ai_reviews[s.id]={**result(suggestion='No.' if i==0 else 'Amazing!'),'id':s.id,'track_id':project.active.id,
            'source_key':ai_review.source_key(project.active,i),'decision':'pending','source_text':s.text,'current_translation':s.translation,
            'protocol_version':2,'verification':'faithful'}
    return project


def test_review_strict_schema_rejects_wrong_ids_inconsistent_ok_and_reasoning():
    assert ai_review.validate_result({'id':result()},'id')['suggested_translation']=='No.'
    for value in ({'other':result()},{'id':result('ok','No.')},
                  {'id':{**result(),'requires_audio_review':1}}, {'id':{**result(),'reason':'<think>Reasoning</think>'}}):
        with pytest.raises(ValueError): ai_review.validate_result(value,'id')


def test_apply_multiple_proposals_checks_all_context_before_any_change():
    project=project_with_results();ids=[s.id for s in project.active.segments]
    assert ai_review.apply_proposals(project,ids)==2
    assert [s.translation for s in project.active.segments]==['No.','Amazing!']
    assert all(s.status=='manual' and s.review_status=='reviewed' for s in project.active.segments)
    assert all(r['decision']=='accepted' for r in project.ai_reviews.values())
    with pytest.raises(ValueError): ai_review.apply_proposals(project,ids)


def test_stale_source_or_neighbour_prevents_overwriting_manual_translation():
    project=project_with_results();ids=[s.id for s in project.active.segments]
    project.active.segments[1].translation='User correction.'
    before=copy.deepcopy(project.to_dict())
    with pytest.raises(ValueError,match='nieaktualna'): ai_review.apply_proposals(project,ids)
    assert project.to_dict()==before
    project=project_with_results();key=ai_review.source_key(project.active,0)
    project.active.segments[0].bookmarked=True
    assert ai_review.source_key(project.active,0)==key
    project.active.segments[1].text='Nie inny kontekst'
    assert ai_review.source_key(project.active,0)!=key


def test_review_worker_emits_proposals_never_translation_and_resumes(tmp_path,monkeypatch):
    project=project_with_results();project.ai_reviews={}
    model=tmp_path/'Qwen3-Instruct.gguf';model.write_bytes(b'GGUFtest')
    spec={'project':project.to_dict(),'backend':'embedded','model_path':str(model),'executable':sys.executable,
          'cache_dir':str(tmp_path/'cache'),'reserve_gib':0,'job_id':'review','mode':'full'}
    calls=[]
    def infer(spec,track,index,folder):
        calls.append(index);return result(suggestion='Correct English.')
    monkeypatch.setattr(ai_review,'infer_review',infer)
    monkeypatch.setattr(ai_review,'verify_suggestion',lambda *a,**kw:'faithful')
    messages=[];emit=lambda kind,**data:messages.append({'type':kind,**data})
    ai_review.run_review(spec,emit)
    assert calls==[0,1] and not any(m['type']=='translation' for m in messages)
    assert project.active.segments[0].translation=='House.'
    for item in messages:
        if item['type']=='ai_review': project.ai_reviews[item['id']]=item['result']
    spec['project']=project.to_dict();calls.clear()
    ai_review.run_review(spec,emit)
    assert calls==[]
    spec['force']=True
    ai_review.run_review(spec,emit)
    assert calls==[0,1]


def test_wrong_source_verification_withholds_proposal_and_marks_uncertainty(tmp_path,monkeypatch):
    project=project_with_results();project.ai_reviews={}
    model=tmp_path/'Qwen3-Instruct.gguf';model.write_bytes(b'GGUFtest')
    spec={'project':project.to_dict(),'backend':'embedded','model_path':str(model),'executable':sys.executable,
          'cache_dir':str(tmp_path/'cache'),'reserve_gib':0,'job_id':'review','mode':'full'}
    monkeypatch.setattr(ai_review,'infer_review',lambda *a,**kw:result(suggestion='Wrong neighbour dialogue.'))
    monkeypatch.setattr(ai_review,'verify_suggestion',lambda *a,**kw:'incorrect')
    messages=[];ai_review.run_review(spec,lambda kind,**data:messages.append({'type':kind,**data}))
    proposals=[m['result'] for m in messages if m['type']=='ai_review']
    assert proposals and all(p['status']=='uncertain' and p['suggested_translation']=='' and p['requires_audio_review'] for p in proposals)
    assert project.active.segments[0].translation=='House.'


def test_automatic_review_applies_only_verified_changes_without_marking_human_reviewed():
    project=project_with_results()
    project.active.segments[1].status='manual'
    assert ai_review.apply_verified_automatically(project)==1
    first,second=project.active.segments
    assert first.translation=='No.' and first.status=='machine' and first.review_status=='unreviewed'
    assert second.translation=='すごい！'
    assert project.ai_reviews[first.id]['current_translation']=='House.'
    assert project.ai_reviews[first.id]['applied_automatically']


def test_automatic_review_withholds_audio_uncertainty_and_remote_context_changes():
    from studio.context_review import source_digest
    project=project_with_results()
    project.ai_reviews[project.active.segments[0].id]['requires_audio_review']=True
    project.ai_reviews[project.active.segments[1].id]['status']='uncertain'
    assert ai_review.apply_verified_automatically(project)==0
    project=project_with_results()
    project.active.segments.extend([Segment(i*10000,i*10000+1000,'他の場面') for i in range(1,8)])
    key=project.active.segments[0].id
    project.ai_reviews[key]['source_key']=ai_review.source_key(project.active,0)
    project.ai_reviews[key]['global_source_key']=source_digest(project.active)
    project.active.segments[-1].text='別の人物の名前'
    with pytest.raises(ValueError,match='kontekst całego filmu'): ai_review.apply_proposals(project,[key])
