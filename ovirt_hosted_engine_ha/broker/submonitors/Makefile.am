#
# ovirt-hosted-engine-ha -- ovirt hosted engine high availability
# Copyright (C) 2012-2013 Red Hat, Inc.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#

include $(top_srcdir)/build/python.inc

MAINTAINERCLEANFILES = \
	$(srcdir)/Makefile.in \
	$(NULL)
CLEANFILES = \
	$(NULL)

brokersubmonitorsdir = $(engine_ha_libdir)/broker/submonitors

dist_brokersubmonitors_PYTHON = \
	cpu_load.py \
	cpu_load_no_engine.py \
	engine_health.py \
	mem_free.py \
	mem_load.py \
	mgmt_bridge.py \
	ping.py \
	$(NULL)

clean-local: \
	python-clean \
	$(NULL)

all-local: \
	$(DISTFILES) \
	python-syntax-check \
	$(NULL)
