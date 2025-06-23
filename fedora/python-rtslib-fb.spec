%global upstream_name rtslib-fb
%global pkg_name rtslib
%global _description %{expand:
rtslib-fb is an object-based Python library for configuring the LIO
generic SCSI target, present in Linux kernel.}

# Package metadata
Name:           python-%{upstream_name}
Version:        2.1.76
Release:        %autorelease
Summary:        API for Linux kernel SCSI target (aka LIO)
License:        Apache-2.0
URL:            https://github.com/open-iscsi/%{upstream_name}

# Sources
Source0:        %{pypi_source %{upstream_name}}
# Man pages from repository
Source1:        %{url}/raw/master/doc/saveconfig.json.5
Source2:        %{url}/raw/master/doc/targetctl.8
Source3:        %{url}/raw/master/doc/getting_started.md

# Architecture
BuildArch:      noarch

# Build requirements
%bcond_without tests
BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  systemd-rpm-macros

# Build backend requirements for hatch
BuildRequires:  hatch
BuildRequires:  python3-hatch-vcs
BuildRequires:  python3-hatchling

%description
%{_description}

# Python subpackage
%package -n python3-%{pkg_name}
Summary:        %{summary}
# Runtime requirements
Requires:       python3-pyudev

%package -n target-restore
Summary:          Systemd service for targetcli/rtslib
Requires:         python3-rtslib = %{version}-%{release}
Requires:         systemd

%description -n target-restore
Systemd service to restore the LIO kernel target settings
on system restart.

%description -n python3-%{pkg_name}
%{_description}

# Build steps
%prep
%autosetup -n %{upstream_name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files rtslib rtslib_fb

# Install systemd service file
mkdir -p %{buildroot}%{_unitdir}
install -p -m 0644 systemd/target.service %{buildroot}%{_unitdir}/target.service

# Install man pages and docs
mkdir -p %{buildroot}%{_mandir}/man5
mkdir -p %{buildroot}%{_mandir}/man8
mkdir -p %{buildroot}%{_docdir}/python3-%{pkg_name}
mkdir -p %{buildroot}%{_sysconfdir}/target/backup
mkdir -p %{buildroot}%{_localstatedir}/target/pr
mkdir -p %{buildroot}%{_localstatedir}/target/alua
install -p -m 0644 %{SOURCE1} %{buildroot}%{_mandir}/man5/saveconfig.json.5
install -p -m 0644 %{SOURCE2} %{buildroot}%{_mandir}/man8/targetctl.8
install -p -m 0644 %{SOURCE3} %{buildroot}%{_docdir}/python3-%{pkg_name}/getting_started.md

%post -n target-restore
%systemd_post target.service

%preun -n target-restore
%systemd_preun target.service

%postun -n target-restore
%systemd_postun_with_restart target.service

# Package contents
%files -n python3-%{pkg_name} -f %{pyproject_files}
%license COPYING
%doc README.md
%{_docdir}/python3-%{pkg_name}/getting_started.md

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
