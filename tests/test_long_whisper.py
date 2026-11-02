from studio.core import Segment,Track
from tools.verify_long_whisper import transcript_diagnostics,progress_tail,native_confidence_diagnostics


def test_long_diagnostics_preserve_invalid_hypotheses_and_do_not_treat_short_replies_as_repeat_runs():
    cues=[Segment(0,0,'raw'),Segment(100,800,'はい'),Segment(900,1700,'はい'),Segment(1800,2300,'はい'),Segment(2400,2900,'はい')]
    cues += [Segment(3000+i*1000,3900+i*1000,'same phrase') for i in range(4)]
    cues += [Segment(30000,31000,'later'),Segment(30500,32000,'overlap')]
    before=[(c.start,c.end,c.text) for c in cues]
    result=transcript_diagnostics(Track('diagnostic',cues),32000)
    assert result['invalid_time_indices']==[0] and result['zero_duration_cues']==1
    assert result['overlap_indices']==[9]
    assert len(result['consecutive_repeat_runs'])==1 and result['consecutive_repeat_runs'][0]['count']==4
    assert result['long_gaps'][0]['duration_ms']==23100
    assert [(c.start,c.end,c.text) for c in cues]==before


def test_live_progress_never_echoes_timestamped_private_dialogue(tmp_path):
    path=tmp_path/'engine.log'
    path.write_text('Standalone Faster-Whisper-XXL running on: CUDA\n'
        'MDX Kim_Vocal_2 model probably is running on CUDA:  20% | 24/120 | 00:40\r'
        '[00:10.000 --> 00:12.000] PRIVATE WARNING: Transcribing private dialogue\n',encoding='utf8')
    lines=progress_tail(path)
    assert len(lines)==2 and 'PRIVATE' not in str(lines)
    assert '20%' in lines[-1]


def test_native_confidence_keeps_missing_coverage_and_requires_both_silence_signals():
    result=native_confidence_diagnostics({'segments':[
        {'avg_logprob':-.2,'compression_ratio':1.5,'no_speech_prob':.9},
        {'avg_logprob':-1.2,'compression_ratio':2.8,'no_speech_prob':.8},
        {'avg_logprob':float('nan'),'no_speech_prob':True}]})
    assert result['segments']==3 and result['field_coverage']['avg_logprob']==2
    assert result['field_coverage']['no_speech_prob']==2
    assert result['high_no_speech']==[0,1] and result['silence_candidates']==[1]
    assert result['low_logprob']==[1] and result['high_compression']==[1]
