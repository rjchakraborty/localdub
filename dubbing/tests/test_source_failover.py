import pytest
import requests

from dubbing import sources


def test_connect_timeout_tries_next_checked_address_without_changing_tls_host(monkeypatch):
    attempts=[]
    monkeypatch.setattr(sources,'public_addresses',lambda url:['8.8.8.8','1.1.1.1'])
    class Session(requests.Session):
        def request(self,method,url,**kwargs):
            adapter=self.adapters['https://']
            attempts.append((adapter.address,adapter.hostname,kwargs['headers']['Host'],self.trust_env))
            if len(attempts)==1:raise requests.ConnectTimeout('First address unavailable')
            response=requests.Response();response.status_code=200
            response._content=b'audio';response._content_consumed=True
            return response
    monkeypatch.setattr(sources.requests,'Session',Session)
    with sources.get_public('https://example.com/audio.mp3') as response:
        assert response.content==b'audio'
    assert attempts==[('8.8.8.8','example.com','example.com',False),('1.1.1.1','example.com','example.com',False)]


def test_tls_failure_is_not_retried(monkeypatch):
    monkeypatch.setattr(sources,'public_addresses',lambda url:['8.8.8.8','1.1.1.1'])
    attempts=[]
    class Session(requests.Session):
        def request(self,*args,**kwargs):
            attempts.append(1)
            raise requests.exceptions.SSLError('Certificate rejected')
    monkeypatch.setattr(sources.requests,'Session',Session)
    with pytest.raises(requests.exceptions.SSLError):
        with sources.get_public('https://example.com/audio.mp3'):pass
    assert len(attempts)==1


def test_error_while_reading_the_body_does_not_replay_the_request(monkeypatch):
    monkeypatch.setattr(sources,'public_addresses',lambda url:['8.8.8.8','1.1.1.1'])
    attempts=[]
    class Session(requests.Session):
        def request(self,*args,**kwargs):
            attempts.append(1)
            response=requests.Response();response.status_code=200
            response._content=b'audio';response._content_consumed=True
            return response
    monkeypatch.setattr(sources.requests,'Session',Session)
    with pytest.raises(requests.ConnectionError,match='Body interrupted'):
        with sources.get_public('https://example.com/audio.mp3'):
            raise requests.ConnectionError('Body interrupted')
    assert len(attempts)==1


def test_unreachable_address_attempts_are_bounded(monkeypatch):
    monkeypatch.setattr(sources,'public_addresses',lambda url:['8.8.8.8']*10)
    attempts=[]
    class Session(requests.Session):
        def request(self,*args,**kwargs):
            attempts.append(1)
            raise requests.ConnectTimeout('Unreachable')
    monkeypatch.setattr(sources.requests,'Session',Session)
    with pytest.raises(requests.ConnectTimeout):
        with sources.get_public('https://example.com/audio.mp3'):pass
    assert len(attempts)==4
