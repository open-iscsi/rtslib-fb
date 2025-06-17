%global upstream_name rtslib-fb
%global pkg_name rtslib

Name:           python-%{upstream_name}
Version:        %{?version}%{!?version:0.0.1}
Release:        %autorelease
Summary:        API for Linux kernel SCSI target (aka LIO)
License:        Apache-2.0
URL:            https://github.com/open-iscsi/%{upstream_name}
Source0:        %{pypi_source %{upstream_name}}

BuildArch:      noarch
# Build requirements
%bcond_without tests
BuildRequires:  python3-devel >= 3.9
BuildRequires:  python3-pip
# Build backend requirements
BuildRequires:  hatch
BuildRequires:  python3-hatch-vcs
BuildRequires:  python3-hatchling
%if %{with tests}
# Test requirements would go here
BuildRequires:  python3-pytest
%endif

%description
rtslib-fb is an object-based Python library for configuring the LIO
generic SCSI target, present in Linux kernel.

%package -n python3-%{pkg_name}
Summary:        %{summary}
Requires:       python3-pyudev >= 0.18
%{?python_provide:%python_provide python3-%{pkg_name}}

%description -n python3-%{pkg_name}
rtslib-fb is an object-based Python library for configuring the LIO
generic SCSI target, present in Linux kernel.

%prep
%autosetup -n %{upstream_name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files rtslib

# Install systemd service file
mkdir -p %{buildroot}%{_unitdir}
install -p -m 644 systemd/target.service %{buildroot}%{_unitdir}/target.service

# Install man pages
mkdir -p %{buildroot}%{_mandir}/man5
mkdir -p %{buildroot}%{_mandir}/man8
install -p -m 644 doc/saveconfig.json.5 %{buildroot}%{_mandir}/man5/
install -p -m 644 doc/targetctl.8 %{buildroot}%{_mandir}/man8/

%check
%if %{with tests}
%pytest
%endif

%files -n python3-%{pkg_name} -f %{pyproject_files}
%license COPYING
%doc README.md
%{_unitdir}/target.service
%{_mandir}/man5/saveconfig.json.5*
%{_mandir}/man8/targetctl.8*

%changelog
%autochangelog
