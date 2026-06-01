%global appdir   /opt/osv-agent
%global venvdir  %{appdir}/venv
%global appuser  osvagent

Name:           osv-agent
Version:        0.1.0
Release:        1%{?dist}
Summary:        OSV Vulnerability Collector Agent (T1)

License:        Proprietary
URL:            https://example.local/osv-agent
# 빌드 입력: agent/ 소스(pyproject.toml + src/)를 tar 로 묶은 것.
# README.md 의 빌드 절차 참고. (osv-agent-%{version}.tar.gz)
Source0:        %{name}-%{version}.tar.gz
Source1:        osv-agent.service
Source2:        osv-agent.env

BuildArch:      noarch

# 런타임 의존성: 시스템 python3 로 venv 만 만들고, pip 로 앱을 설치한다.
Requires:       python3 >= 3.9
Requires:       python3-pip
%{?systemd_requires}

%description
T1 Public 노드에서 OSV API 로 취약점 데이터를 수집해 T2 로 보고하는
Python 기반 커스텀 에이전트. 전용 venv(%{venvdir}) 에 설치되고
systemd 서비스(osv-agent.service)로 구동된다.

%prep
%autosetup -n %{name}-%{version}

%build
# noarch: 빌드 단계 없음. 소스를 그대로 설치 트리에 배치한다.

%install
# 1) 앱 소스 배치 (%post 에서 이 소스로 venv 에 설치)
install -d -m 0750 %{buildroot}%{appdir}/src
cp -a pyproject.toml src %{buildroot}%{appdir}/src/
install -d -m 0750 %{buildroot}%{venvdir}

# 2) systemd unit
install -D -m 0644 %{SOURCE1} %{buildroot}%{_unitdir}/%{name}.service

# 3) 환경설정 (업데이트 시 사용자 수정 보존 → %config(noreplace))
install -D -m 0640 %{SOURCE2} %{buildroot}%{_sysconfdir}/osv-agent.env

%pre
# 전용 시스템 계정 생성 (이미 있으면 무시)
getent group %{appuser} >/dev/null || groupadd -r %{appuser}
getent passwd %{appuser} >/dev/null || \
    useradd -r -g %{appuser} -d %{appdir} -s /sbin/nologin \
            -c "OSV Agent service account" %{appuser}
exit 0

%post
# 최초 설치/업그레이드 시 venv 생성 + 앱 설치 (T1은 인터넷 직결 → pip 가능)
if [ ! -x %{venvdir}/bin/python ]; then
    python3 -m venv %{venvdir}
fi
%{venvdir}/bin/pip install --upgrade pip >/dev/null 2>&1 || :
%{venvdir}/bin/pip install --upgrade %{appdir}/src
chown -R %{appuser}:%{appuser} %{appdir}
%systemd_post %{name}.service

%preun
%systemd_preun %{name}.service

%postun
%systemd_postun_with_restart %{name}.service
# 완전 제거(uninstall, $1==0)시에만 venv 정리. 업그레이드($1==1)에서는 보존.
if [ $1 -eq 0 ]; then
    rm -rf %{venvdir}
fi

%files
%dir %{appdir}
%dir %{appdir}/src
%{appdir}/src/pyproject.toml
%{appdir}/src/src
%dir %{venvdir}
%{_unitdir}/%{name}.service
%config(noreplace) %{_sysconfdir}/osv-agent.env

%changelog
* Thu May 29 2026 lab_ai3 <lab_ai3@icomsoft.co.kr> - 0.1.0-1
- 초기 패키지: venv 기반 에이전트 + systemd 서비스
