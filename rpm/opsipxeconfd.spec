#
# spec file for package opsipxeconfd
#
# Copyright (c) 2010 uib GmbH.
# This file and all modifications and additions to the pristine
# package are under the same license as the package itself.
#

Name:           opsipxeconfd
BuildRequires:  python-devel python-setuptools
Requires:       opsi-atftp python-opsi >= 4.0 opsi-linux-bootimage
Url:            http://www.opsi.org
License:        GPL v2 or later
Group:          Productivity/Networking/Opsi
AutoReqProv:    on
Version:        4.0.4.1
Release:        2
Summary:        opsi pxe configuration daemon
%define tarname opsipxeconfd
Source:         opsipxeconfd_4.0.4.1-2.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-build
%if 0%{?sles_version}
BuildRequires: python-opsi >= 4.0.1 zypper logrotate
%endif
%if 0%{?suse_version}
Suggests: logrotate
BuildRequires: zypper logrotate
PreReq: %insserv_prereq zypper
%{py_requires}
%endif
%if 0%{?suse_version} != 1110
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

#fix for runlevel 4 (not used on rpm-based machines)
if [ -e "/etc/init.d/opsipxeconfd" ]; then
	sed -i "s/2 3 4 5/2 3 5/g; s/2345/235/g" /etc/init.d/opsipxeconfd
fi

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

%if 0%{?suse_version} || 0%{?sles_version}
LOGROTATE_VERSION="$(zypper info logrotate | grep -i "version" | awk '{print $2}' | cut -d '-' -f 1)"
if [ "$(zypper --terse versioncmp $LOGROTATE_VERSION 3.8)" == "-1" ]; then
        LOGROTATE_TEMP=/tmp/opsi-logrotate_config
        grep -v "su root opsiadmin" /etc/logrotate.d/opsipxeconfd > $LOGROTATE_TEMP
        mv $LOGROTATE_TEMP /etc/logrotate.d/opsipxeconfd
fi
%else
        %if 0%{?rhel_version} || 0%{?centos_version}
                # Currently neither RHEL nor CentOS ship an logrotate > 3.8
                # Maybe some day in the future RHEL / CentOS will have a way for easy version comparison
                # LOGROTATE_VERSION="$(yum list logrotate | grep "installed$" | awk '{ print $2 }' | cut -d '-' -f 1)"
                LOGROTATE_TEMP=/tmp/opsi-logrotate_config
                grep -v "su root opsiadmin" /etc/logrotate.d/opsipxeconfd > $LOGROTATE_TEMP
                mv $LOGROTATE_TEMP /etc/logrotate.d/opsipxeconfd
        %endif
%endif

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
