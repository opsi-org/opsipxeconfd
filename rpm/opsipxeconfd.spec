#
# spec file for package opsipxeconfd
#
# Copyright (c) 2008 uib GmbH.
# This file and all modifications and additions to the pristine
# package are under the same license as the package itself.
#

Name:           opsipxeconfd
Requires:       opsi-atftp python-opsi opsi-linux-bootimage
PreReq:         %insserv_prereq
Url:            http://www.opsi.org
License:        GPL v2 or later
Group:          Productivity/Networking/Opsi
AutoReqProv:    on
Version:        3.4.99
Release:        1
Summary:        OPSI PXE configuration daemon
%define tarname opsipxeconfd
Source:         %{tarname}-%{version}.tar.bz2
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
BuildArch:      noarch
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
mkdir -p $RPM_BUILD_ROOT/etc/logrotate.d
mkdir -p $RPM_BUILD_ROOT/var/log/opsi
install -m 0755 src/opsipxeconfd $RPM_BUILD_ROOT/usr/sbin/
install -m 0644 files/opsipxeconfd.conf $RPM_BUILD_ROOT/etc/opsi/
install -m 0755 debian/opsipxeconfd.init $RPM_BUILD_ROOT/etc/init.d/opsipxeconfd
install -m 0644 debian/opsipxeconfd.logrotate $RPM_BUILD_ROOT/etc/logrotate.d/opsipxeconfd
ln -sf ../../etc/init.d/opsipxeconfd $RPM_BUILD_ROOT/usr/sbin/rcopsipxeconfd

# ===[ clean ]======================================
%clean
rm -rf $RPM_BUILD_ROOT

# ===[ post ]=======================================
%post
#%{fillup_and_insserv opsipxeconfd}
insserv opsipxeconfd

# update?
if [ ${FIRST_ARG:-0} -gt 1 ]; then
	if [ -e /var/run/opsipxeconfd.pid -o -e /var/run/opsipxeconfd/opsipxeconfd.pid ]; then
		rm /var/run/opsipxeconfd.pid
		/etc/init.d/opsipxeconfd restart || true
	fi
else
	/etc/init.d/opsipxeconfd start || true
fi

# Moved to /var/run/opsipxeconfd/opsipxeconfd.socket
rm '/var/run/opsipxeconfd.socket' >/dev/null 2>&1 || true

# ===[ preun ]======================================
%preun
%stop_on_removal opsipxeconfd

# ===[ postun ]=====================================
%postun
%restart_on_update opsipxeconfd
if [ $1 -eq 0 ]; then
	%insserv_cleanup
fi


# ===[ files ]======================================
%files
# default attributes
%defattr(-,root,root)

# documentation
#%doc LICENSE README RELNOTES doc

# configfiles
%config(noreplace) /etc/opsi/opsipxeconfd.conf
%attr(0755,root,root) %config /etc/init.d/opsipxeconfd
%config /etc/logrotate.d/opsipxeconfd

# other files
%attr(0755,root,root) /usr/sbin/opsipxeconfd
%attr(0755,root,root) /usr/sbin/rcopsipxeconfd

# directories
%attr(0755,pcpatch,root) %dir /etc/opsi
%dir /var/log/opsi

# ===[ changelog ]==================================
%changelog
* Fri Sep 19 2008 - j.schneider@uib.de
- created new package









