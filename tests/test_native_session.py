import pytest
from studio import native_session


def test_session_is_lazy_during_asr_and_restores_outer_context(tmp_path):
    assert native_session.ACTIVE.get() is None
    with native_session.inference_session(tmp_path/'outer') as outer:
        assert outer.process is None and not (tmp_path/'outer').exists()
        with pytest.raises(RuntimeError):
            with native_session.inference_session(tmp_path/'inner') as inner:
                assert native_session.ACTIVE.get() is inner
                raise RuntimeError('failed request')
        assert native_session.ACTIVE.get() is outer
    assert native_session.ACTIVE.get() is None


def test_failure_closes_connection_job_and_process(tmp_path,monkeypatch):
    events=[]
    class Process:
        stopped=False
        def poll(self): return 1 if self.stopped else None
        def kill(self): events.append('kill');self.stopped=True
        def wait(self,timeout): events.append('wait');assert self.stopped
    class Job:
        def close(self): events.append('job')
    class Client:
        def close(self): events.append('client')
    session=native_session.NativeSession(tmp_path)
    session.process=Process();session.job=Job();session.client=Client()
    monkeypatch.setattr(native_session,'NativeSession',lambda root:session)
    with pytest.raises(ValueError):
        with native_session.inference_session(tmp_path): raise ValueError('malformed or failed stage')
    assert events==['client','job','kill','wait']
    assert session.process is None and session.job is None and session.client is None
    assert native_session.ACTIVE.get() is None
