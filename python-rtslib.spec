%global pypi_name rtslib_fb

Name:           python-rtslib
Version:        0.0.0
Release:        %autorelease
Summary:        API for Linux kernel LIO SCSI target
License:        Apache-2.0
URL:            https://github.com/open-iscsi/rtslib-fb
Source:         %{pypi_source %{pypi_name}}

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  systemd-rpm-macros

%global _description %{expand:
API for generic Linux SCSI kernel target. Includes the 'target'
service and targetctl tool for restoring configuration.}

%description %_description

%package -n python3-rtslib
Summary:        %{summary}
Requires:       python3-kmod

%description -n python3-rtslib %_description

%package -n target-restore
Summary:          Systemd service for targetcli/rtslib
Requires:         python3-rtslib = %{version}-%{release}
Requires:         systemd

%description -n target-restore
Systemd service to restore the LIO kernel target settings
on system restart.

%prep
%autosetup -p1 -n %{pypi_name}-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l 'rtslib*'

mkdir -p %{buildroot}%{_unitdir}
mkdir -p %{buildroot}%{_mandir}/man8/
mkdir -p %{buildroot}%{_mandir}/man5/
mkdir -p %{buildroot}%{_sysconfdir}/target/backup
mkdir -p %{buildroot}%{_localstatedir}/target/pr
mkdir -p %{buildroot}%{_localstatedir}/target/alua
install -m 644 systemd/target.service %{buildroot}%{_unitdir}/target.service
install -m 644 doc/targetctl.8 %{buildroot}%{_mandir}/man8/
install -m 644 doc/saveconfig.json.5 %{buildroot}%{_mandir}/man5/

%check
%pyproject_check_import

%post -n target-restore
%systemd_post target.service

%preun -n target-restore
%systemd_preun target.service

%postun -n target-restore
%systemd_postun_with_restart target.service

%files -n python3-rtslib -f %{pyproject_files}
%doc README.md doc/getting_started.md

%files -n target-restore
%{_bindir}/targetctl
%{_unitdir}/target.service
%dir %{_sysconfdir}/target
%dir %{_sysconfdir}/target/backup
%dir %{_localstatedir}/target
%dir %{_localstatedir}/target/pr
%dir %{_localstatedir}/target/alua
%{_mandir}/man8/targetctl.8*
%{_mandir}/man5/saveconfig.json.5*

%changelog
%autochangelog
