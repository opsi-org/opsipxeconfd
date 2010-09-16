#
# spec file for package opsipxeconfd
#
# Copyright (c) 2010 uib GmbH.
# This file and all modifications and additions to the pristine
# package are under the same license as the package itself.
#

Name:           opsipxeconfd
BuildRequires:  python-devel python-setuptools python-opsi >= 3.99
Requires:       opsi-atftp python-opsi >= 3.99 opsi-linux-bootimage
Url:            http://www.opsi.org
License:        GPL v2 or later
Group:          Productivity/Networking/Opsi
AutoReqProv:    on
Version:        3.99.2
Release:        1
Summary:        opsi pxe configuration daemon
%define tarname opsipxeconfd
Source:         opsipxeconfd_3.99.2-1.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
%if 0%{?suse_version}
PreReq:         %insserv_prereq
%{py_requires}
%endif
%if 0%{?centos_version} || 0%{?rhel_version} || 0%{?fedora_version}
BuildArch:      noarch
%endif

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
python setup.py build

# ===[ install ]====================================
%install
%if 0%{?suse_version}
python setup.py install --prefix=%{_prefix} --root=$RPM_BUILD_ROOT --record-rpm=INSTALLED_FILES
%else
python setup.py install --prefix=%{_prefix} --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES
%endif
mkdir -p $RPM_BUILD_ROOT/var/log/opsi
mkdir -p $RPM_BUILD_ROOT/usr/sbin
ln -sf /etc/init.d/opsipxeconfd $RPM_BUILD_ROOT/usr/sbin/rcopsipxeconfd

%if 0%{?sles_version}
	sed -i 's#^pxe config template = /tftpboot/linux/pxelinux.cfg/install#pxe config template = /var/lib/tftpboot/opsi/pxelinux.cfg/install#;s#^pxe config dir = /tftpboot/linux/pxelinux.cfg#pxe config dir = /var/lib/tftpboot/opsi/pxelinux.cfg#' $RPM_BUILD_ROOT/etc/opsi/opsipxeconfd.conf
%endif

sed -i 's#/etc/init.d$##;s#/etc/logrotate.d$##' INSTALLED_FILES

# ===[ clean ]======================================
%clean
rm -rf $RPM_BUILD_ROOT

# ===[ post ]=======================================
%post
if [ $1 -eq 1 ]; then
	# Install
	#%{fillup_and_insserv opsipxeconfd}
	
	%if 0%{?centos_version} || 0%{?rhel_version} || 0%{?fedora_version}
	chkconfig --add opsipxeconfd
	%else
	insserv opsipxeconfd || true
	%endif
	
	/etc/init.d/opsipxeconfd start || true
else
	# Upgrade
	# Moved to /var/run/opsipxeconfd/opsipxeconfd.socket
	rm /var/run/opsipxeconfd.socket >/dev/null 2>&1 || true
	
	if [ -e /var/run/opsipxeconfd.pid -o -e /var/run/opsipxeconfd/opsipxeconfd.pid ]; then
		rm /var/run/opsipxeconfd.pid >/dev/null 2>&1 || true
		/etc/init.d/opsipxeconfd restart || true
	fi
fi

# ===[ preun ]======================================
%preun
%stop_on_removal opsipxeconfd

# ===[ postun ]=====================================
%postun
%restart_on_update opsipxeconfd
if [ $1 -eq 0 ]; then
	%if 0%{?centos_version} || 0%{?rhel_version} || 0%{?fedora_version}
		chkconfig --del opsipxeconfd
	%else
		%insserv_cleanup
	%endif
fi


# ===[ files ]======================================
%files -f INSTALLED_FILES
# default attributes
%defattr(-,root,root)

# documentation
#%doc LICENSE README RELNOTES doc

# configfiles
%config(noreplace) /etc/opsi/opsipxeconfd.conf
%attr(0755,root,root) %config /etc/init.d/opsipxeconfd
%config /etc/logrotate.d/opsipxeconfd

# other files
%attr(0755,root,root) /usr/bin/opsipxeconfd
%attr(0755,root,root) /usr/sbin/rcopsipxeconfd

# directories
%attr(0755,pcpatch,root) %dir /etc/opsi
%dir /var/log/opsi

# ===[ changelog ]==================================
%changelog
