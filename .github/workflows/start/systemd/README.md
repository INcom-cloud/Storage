# systemd 참고 unit

Ansible 없이 **수동(bare systemd)** 으로 설치할 때 참고용 정적 unit 파일.
정식 배포는 `../ansible/roles/*/templates/*.service.j2` (변수 치환) 를 사용한다.

수동 설치 흐름:

```bash
# 1) 에이전트 패키지 설치
sudo python3 -m venv /opt/osv-agent/venv
sudo /opt/osv-agent/venv/bin/pip install /path/to/agent

# 2) 환경파일/유닛 배치
sudo cp osv-agent.env   /etc/osv-agent.env
sudo cp osv-agent.service /etc/systemd/system/

# 3) 기동 + 디버그 로그 확인
sudo systemctl daemon-reload
sudo systemctl enable --now osv-agent
journalctl -u osv-agent -f      # ← 디버그 콘솔 출력 / error·fail 확인
```
