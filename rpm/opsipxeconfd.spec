#
# spec file for package opsipxeconfd
#
# Copyright (c) 2010-2018 uib GmbH.
# This file and all modifications and additions to the pristine
# package are under the same license as the package itself.
#

Name:           opsipxeconfd
BuildRequires:  systemd
Requires:       opsi-tftpd
Requires:       opsi-linux-bootimage
Requires:       python-opsi >= 4.1.1.76
Requires:       systemd
%{?systemd_requires}
BuildArch:      noarch
Url:            http://www.opsi.org
License:        AGPL-3.0+
Group:          Productivity/Networking/Opsi
AutoReqProv:    on
Version:        4.1.1.18
Release:        1
Summary:        This is the opsi pxe configuration daemon
Source:         opsipxeconfd_4.1.1.18-1.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build

%if 0%{?sles_version} || 0%{?suse_version} == 1315
# SLES
BuildRequires: logrotate
BuildRequires: python-opsi >= 4.1
BuildRequires: zypper
%endif

%if 0%{?rhel_version} >= 800 || 0%{?centos_version} >= 800
BuildRequires:  python2-devel
BuildRequires:  python2-setuptools
%else
BuildRequires:  python-devel
BuildRequires:  python-setuptools
%endif

%if 0%{?suse_version}
Suggests: logrotate
BuildRequires: zypper logrotate
%if 0%{?suse_version} >= 1210
BuildRequires: systemd-rpm-macros
%endif
%{py_requires}
%endif

%define tarname opsipxeconfd
%define toplevel_dir %{name}-%{version}

# ===[ description ]================================
%description
This package contains the opsi pxe configuration daemon.

# ===[ debug_package ]==============================
%debug_package

# ===[ prep ]=======================================
%prep

# ===[ setup ]======================================
%setup -n %{tarname}-%{version}

# ===[ build ]======================================
%build
export CFLAGS="$RPM_OPT_FLAGS"
%if 0%{?rhel_version} >= 700 || 0%{?centos_version} >= 700
# Fix for https://bugzilla.redhat.com/show_bug.cgi?id=1117878
export PATH="/usr/bin:$PATH"
%endif
python2 setup.py build

# ===[ pre ]========================================
%pre
%if 0%{?suse_version}
%service_add_pre opsipxeconfd.service
%endif

# ===[ install ]====================================
%install

%if 0%{?suse_version}
python2 setup.py install --prefix=%{_prefix} --root=$RPM_BUILD_ROOT --record-rpm=INSTALLED_FILES
%else
python2 setup.py install --prefix=%{_prefix} --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES
%endif
mkdir -p $RPM_BUILD_ROOT/var/log/opsi

sed -i 's#/etc/logrotate.d$##' INSTALLED_FILES

%if 0%{?suse_version} >= 1315 || 0%{?centos_version} >= 700 || 0%{?rhel_version} >= 700
    # Adjusting to the correct service names
    sed --in-place "s/=smbd.service/=smb.service/" "debian/opsipxeconfd.service" || true
    sed --in-place "s/=isc-dhcp-server.service/=dhcpd.service/" "debian/opsipxeconfd.service" || true
%endif

%if 0%{?suse_version}
    # Adjust the path for the PXE netboot template
    sed -i 's#^pxe config template = /tftpboot/linux/pxelinux.cfg/install#pxe config template = /var/lib/tftpboot/opsi/pxelinux.cfg/install#;s#^pxe config dir = /tftpboot/linux/pxelinux.cfg#pxe config dir = /var/lib/tftpboot/opsi/pxelinux.cfg#' $RPM_BUILD_ROOT/etc/opsi/opsipxeconfd.conf

    # Adjust the path for uefi netboot templates on SUSE.
    sed -i 's#^uefi netboot config template x86 = /tftpboot/linux/pxelinux.cfg/install-elilo-x86#uefi netboot config template x86 = /var/lib/tftpboot/opsi/pxelinux.cfg/install-elilo-x86#' $RPM_BUILD_ROOT/etc/opsi/opsipxeconfd.conf
    sed -i 's#^uefi netboot config template x64 = /tftpboot/linux/pxelinux.cfg/install-elilo-x64#uefi netboot config template x64 = /var/lib/tftpboot/opsi/pxelinux.cfg/install-elilo-x64#' $RPM_BUILD_ROOT/etc/opsi/opsipxeconfd.conf
%endif

MKDIR_PATH=$(which mkdir)
CHOWN_PATH=$(which chown)
sed --in-place "s!=-/bin/mkdir!=-$MKDIR_PATH!" "debian/opsipxeconfd.service" || true
sed --in-place "s!=-/bin/chown!=-$CHOWN_PATH!" "debian/opsipxeconfd.service" || true

install -D -m 644 debian/opsipxeconfd.service %{buildroot}%{_unitdir}/opsipxeconfd.service

# ===[ clean ]======================================
%clean
rm -rf $RPM_BUILD_ROOT

# ===[ post ]=======================================
%post

%if 0%{?rhel_version} || 0%{?centos_version}
%systemd_post opsipxeconfd.service
%else
%service_add_post opsipxeconfd.service
%endif

systemctl=`which systemctl`
$systemctl enable opsipxeconfd.service && echo "Enabled opsipxeconfd.service" || echo "Enabling opsipxeconfd.service failed!"
if [ "$1" -eq 1 ]; then
    # Install
    $systemctl start opsipxeconfd.service || true
else
    # Upgrade
    $systemctl restart opsipxeconfd.service || true
fi

# ===[ preun ]======================================
%preun
%if 0%{?rhel_version} || 0%{?centos_version}
%systemd_preun opsipxeconfd.service
%else
%service_del_preun opsipxeconfd.service
%endif

# ===[ postun ]=====================================
%postun
%if 0%{?rhel_version} || 0%{?centos_version}
%systemd_postun opsipxeconfd.service
%else
%service_del_postun opsipxeconfd.service
%endif

# ===[ files ]======================================
%files -f INSTALLED_FILES
# default attributes
%defattr(-,root,root)

%{_unitdir}/opsipxeconfd.service

# configfiles
%config(noreplace) /etc/opsi/opsipxeconfd.conf
%config /etc/logrotate.d/opsipxeconfd

# other files
%attr(0755,root,root) /usr/bin/opsipxeconfd

# directories
%attr(0755,pcpatch,root) %dir /etc/opsi
%dir /var/log/opsi

# ===[ changelog ]==================================
%changelog
