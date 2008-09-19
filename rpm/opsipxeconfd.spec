#
# spec file for package opsipxeconfd
#
# Copyright (c) 2008 uib GmbH.
# This file and all modifications and additions to the pristine
# package are under the same license as the package itself.
#

Name:           opsipxeconfd
Requires:       opsi-atftpd python-opsi opsi-linux-bootimage
PreReq:         %insserv_prereq
Url:            http://www.opsi.org
License:        GPL v2 or later
Group:          Productivity/Networking/Opsi
AutoReqProv:    on
Version:        0.3.4
Release:        2
Summary:        OPSI PXE configuration daemon
%define tarname opsipxeconfd
Source:         %{tarname}-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
%{py_requires}

# ===[ description ]================================
%description
This package contains the OPSI PXE configuration daemon.

# ===[ debug_package ]==============================
%debug_package

# ===[ prep ]=======================================
%prep

# ===[ setup ]======================================
%setup -n %{tarname}-%{version}

# ===[ build ]======================================
%build

# ===[ install ]====================================
%install
mkdir -p $RPM_BUILD_ROOT/usr/sbin
mkdir -p $RPM_BUILD_ROOT/etc/opsi
mkdir -p $RPM_BUILD_ROOT/etc/init.d
install -m 0755 opsipxeconfd $RPM_BUILD_ROOT/usr/sbin/
install -m 0644 files/opsipxeconfd.conf $RPM_BUILD_ROOT/etc/opsi/
install -m 0755 debian/opsipxeconfd.init $RPM_BUILD_ROOT/etc/init.d/opsipxeconfd
ln -sf ../../etc/init.d/opsipxeconfd $RPM_BUILD_ROOT/usr/sbin/rcopsipxeconfd

# ===[ clean ]======================================
%clean
rm -rf $RPM_BUILD_ROOT

# ===[ post ]=======================================
%post
%{fillup_and_insserv opsipxeconfd}

# update?
if [ ${FIRST_ARG:-0} -gt 1 ]; then
	if [ -e /var/run/opsipxeconfd.pid ]; then
		/etc/init.d/opsipxeconfd restart
	fi
fi

# ===[ preun ]======================================
%preun
%stop_on_removal opsipxeconfd

# ===[ postun ]=====================================
%postun
%restart_on_update opsipxeconfd
%insserv_cleanup

# ===[ files ]======================================
%files
# default attributes
%defattr(-,root,root)

# documentation
#%doc LICENSE README RELNOTES doc

# configfiles
%config(noreplace) /etc/opsi/opsipxeconfd.conf
%attr(0755,root,root) %config /etc/init.d/opsipxeconfd

# other files
%attr(0755,root,root) /usr/sbin/opsipxeconfd
%attr(0755,root,root) /usr/sbin/rcopsipxeconfd

# directories
%attr(0755,pcpatch,root) %dir /etc/opsi

# ===[ changelog ]==================================
%changelog
* Fri Sep 19 2008 - j.schneider@uib.de
- created new package









