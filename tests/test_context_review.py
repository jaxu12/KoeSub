import pytest
from studio.context_review import overview,coherence
from studio.core import Segment,Track


def test_whole_film_context_consumes_all_chunks_and_resumes_without_requests(tmp_path):
    track=Track('Film',[Segment(i*1000,i*1000+1000,'名前と学校の場面。'*15) for i in range(14)])
    seen=[]
    def request(instruction,payload,schema,folder):
        if 'source_range' in payload:
            first,last=payload['source_range'];seen.extend(range(first,last+1))
            assert 'do not invent' in instruction
        return {'overview':'Students introduce themselves at school. Names remain tentative.'}
    result=overview(track,request,tmp_path)
    assert seen==list(range(len(track.segments))) and result['chunks']>1
    assert overview(track,lambda *a:pytest.fail('completed context must resume'),tmp_path)==result
    track.segments[-1].text='Changed distant scene'
    with pytest.raises(ValueError,match='Zmieniono JP'): overview(track,request,tmp_path)


def test_coherence_retains_terms_from_distant_chunks_and_flags_bad_protocol(tmp_path):
    track=Track('Film',[Segment(i*1000,i*1000+1000,'田中です。',translation='Tanaka.' if i<6 else 'Suzuki.') for i in range(8)])
    def request(instruction,payload,schema,folder):
        if payload['targets'][0]['en']=='Suzuki.':
            assert 'Tanaka' in payload['previous_continuity_notes']
        return {**{s['id']:'name' if s['en']=='Suzuki.' else 'ok' for s in payload['targets']},'memory':'Tanaka is the established name.'}
    result=coherence(track,'Introductions.',request,tmp_path)
    assert all(result['decisions'][s.id]=='name' for s in track.segments[6:])
    assert coherence(track,'Introductions.',lambda *a:pytest.fail('must resume'),tmp_path)==result
    bad=coherence(track,'Introductions.',lambda *a:{'invented-id':'ok'},tmp_path/'bad')
    assert set(bad['decisions'].values())=={'uncertain'}


def test_overview_combines_earlier_and_later_parts_instead_of_overwriting_memory(tmp_path):
    track=Track('Whole',[Segment(i*1000,i*1000+1000,f'場面{i}。'+('説明。'*65)) for i in range(16)])
    parts=[];combined=[]
    def request(instruction,payload,schema,folder):
        assert 'previous_overview' not in payload
        if 'source_range' in payload:
            first,last=payload['source_range'];text=f'Facts from scenes {first} through {last}.'
            parts.append(text);return {'overview':text}
        notes=payload['chronological_excerpt_summaries'];combined.extend(notes)
        return {'overview':'Beginning, middle and ending facts are retained together.'}
    result=overview(track,request,tmp_path)
    assert len(parts)>1 and all(part in combined for part in parts)
    assert result['part_summaries']==parts
    assert result['overview']=='Beginning, middle and ending facts are retained together.'
