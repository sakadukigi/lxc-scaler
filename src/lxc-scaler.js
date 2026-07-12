/* LXC Auto-Scaler panel for Proxmox VE */
(function () {

    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    function cfgApi() { return 'https://' + window.location.hostname + ':8087/config'; }

    Ext.define('PVE.lxcscaler.Panel', {
        extend: 'Ext.panel.Panel',
        xtype: 'pveLxcScalerPanel',
        onlineHelp: 'pve_admin_guide',
        border: false,
        scrollable: 'y',
        layout: { type: 'vbox', align: 'stretch' },

        initComponent: function () {
            var me = this;
            me.allData = {};
            me.selectedVmid = null;

            me.eventStore = Ext.create('Ext.data.JsonStore', {
                fields: ['time', 'resource', 'old', 'new_val', 'dir', 'reason'],
                data: []
            });

            me.memStore = Ext.create('Ext.data.JsonStore', {
                fields: ['time', 'mem_allocated', 'mem_used'],
                data: []
            });

            me.cpuStore = Ext.create('Ext.data.JsonStore', {
                fields: ['time', 'cpu_allocated', 'cpu_used'],
                data: []
            });

            me.items = [
                {
                    xtype: 'toolbar',
                    itemId: 'ctToolbar',
                    items: [{ xtype: 'tbtext', html: '<b>Container:</b>&nbsp;' }]
                },
                {
                    xtype: 'proxmoxRRDChart',
                    itemId: 'memChart',
                    title: gettext('Memory'),
                    height: 300,
                    width: null,
                    fields: ['mem_allocated', 'mem_used'],
                    fieldTitles: [gettext('Allocated'), gettext('Used')],
                    unit: 'bytes',
                    powerOfTwo: true,
                    colors: ['#115fa6', '#94ae0a'],
                    store: me.memStore
                },
                {
                    xtype: 'proxmoxRRDChart',
                    itemId: 'cpuChart',
                    title: gettext('CPU Cores'),
                    height: 300,
                    width: null,
                    fields: ['cpu_allocated', 'cpu_used'],
                    fieldTitles: [gettext('Allocated'), gettext('Used')],
                    store: me.cpuStore
                },
                {
                    xtype: 'grid',
                    itemId: 'eventsGrid',
                    title: gettext('Scale Events'),
                    height: 220,
                    store: me.eventStore,
                    columns: [
                        { text: gettext('Time'), dataIndex: 'time', width: 155 },
                        { text: gettext('Resource'), dataIndex: 'resource', width: 80 },
                        { text: gettext('Old'), dataIndex: 'old', width: 70, align: 'right' },
                        { text: gettext('New'), dataIndex: 'new_val', width: 70, align: 'right' },
                        {
                            text: '', dataIndex: 'dir', width: 50, align: 'center',
                            renderer: function (v) {
                                return v > 0
                                    ? '<span style="color:#4c4;font-size:14px">&#9650;</span>'
                                    : '<span style="color:#c44;font-size:14px">&#9660;</span>';
                            }
                        },
                        { text: gettext('Reason'), dataIndex: 'reason', flex: 1 }
                    ]
                },
                {
                    xtype: 'panel',
                    title: gettext('Configuration'),
                    collapsible: true,
                    collapsed: false,
                    border: true,
                    margin: '4 0 0 0',
                    bodyPadding: 8,
                    layout: { type: 'vbox', align: 'stretch' },
                    items: [
                        {
                            xtype: 'component',
                            html: '<span style="color:#888">Config API: ' +
                                '<a href="' + cfgApi() + '" target="_blank">' + cfgApi() + '</a>' +
                                ' &mdash; 初回は上記リンクで証明書を許可してから Load してください。</span>'
                        },
                        {
                            xtype: 'component',
                            itemId: 'cfgStatus',
                            html: '',
                            margin: '2 0 0 0'
                        },
                        {
                            xtype: 'container',
                            margin: '4 0 0 0',
                            layout: { type: 'hbox', align: 'stretchmax' },
                            items: [
                                {
                                    xtype: 'fieldset',
                                    title: gettext('Memory'),
                                    flex: 1,
                                    layout: 'anchor',
                                    defaults: { xtype: 'numberfield', anchor: '100%', allowDecimals: false, minValue: 0, labelWidth: 180 },
                                    items: [
                                        { fieldLabel: gettext('Min (MB)'), itemId: 'cfgMemMin', minValue: 16 },
                                        { fieldLabel: gettext('Max (MB)'), itemId: 'cfgMemMax', minValue: 16 },
                                        { fieldLabel: gettext('Scale-down threshold (%)'), itemId: 'cfgMemLow', maxValue: 100 },
                                        { fieldLabel: gettext('Scale-up threshold (%)'), itemId: 'cfgMemHigh', maxValue: 100 }
                                    ]
                                },
                                {
                                    xtype: 'fieldset',
                                    title: gettext('CPU'),
                                    flex: 1,
                                    margin: '0 0 0 8',
                                    layout: 'anchor',
                                    defaults: { xtype: 'numberfield', anchor: '100%', allowDecimals: false, minValue: 1, labelWidth: 160 },
                                    items: [
                                        { fieldLabel: gettext('Min cores'), itemId: 'cfgCpuMin' },
                                        { fieldLabel: gettext('Max cores'), itemId: 'cfgCpuMax' },
                                        { fieldLabel: gettext('Scale-down pressure (%)'), itemId: 'cfgCpuLow', minValue: 0, maxValue: 100 },
                                        { fieldLabel: gettext('Scale-up pressure (%)'), itemId: 'cfgCpuHigh', minValue: 0, maxValue: 100 }
                                    ]
                                },
                                {
                                    xtype: 'fieldset',
                                    title: gettext('Interval'),
                                    flex: 1,
                                    margin: '0 0 0 8',
                                    layout: 'anchor',
                                    defaults: { xtype: 'numberfield', anchor: '100%', allowDecimals: false, minValue: 0, labelWidth: 140 },
                                    items: [
                                        { fieldLabel: gettext('Cooldown (sec)'), itemId: 'cfgCooldown' }
                                    ]
                                }
                            ]
                        },
                        {
                            xtype: 'fieldset',
                            title: gettext('Per-container overrides (JSON)'),
                            margin: '8 0 0 0',
                            layout: 'fit',
                            items: [{
                                xtype: 'textarea',
                                itemId: 'cfgContainers',
                                height: 100,
                                style: 'font-family: monospace; font-size: 12px',
                                emptyText: '{ "100": { "mem_max_mb": 4096, "cpu_max": 4 } }'
                            }]
                        },
                        {
                            xtype: 'container',
                            margin: '8 0 0 0',
                            layout: { type: 'hbox', pack: 'end' },
                            items: [
                                {
                                    xtype: 'button',
                                    text: gettext('Load'),
                                    iconCls: 'fa fa-refresh',
                                    margin: '0 8 0 0',
                                    handler: function () { me.loadConfig(); }
                                },
                                {
                                    xtype: 'button',
                                    text: gettext('Save'),
                                    iconCls: 'fa fa-save',
                                    handler: function () { me.saveConfig(); }
                                }
                            ]
                        }
                    ]
                }
            ];

            me.callParent();
            me.loadData();
            me.on('afterrender', function () { me.loadConfig(); }, me, { single: true });

            me.refreshTask = Ext.TaskManager.start({
                run: me.loadData,
                scope: me,
                interval: 60000
            });
        },

        loadData: function () {
            var me = this;
            Ext.Ajax.request({
                url: '/pve2/js/lxcscaler-data.json?_=' + Date.now(),
                success: function (resp) {
                    try {
                        me.allData = Ext.decode(resp.responseText);
                        me.updateToolbar();
                        var vmids = Object.keys(me.allData);
                        if (vmids.length > 0) {
                            var sel = (me.selectedVmid && me.allData[me.selectedVmid]) ? me.selectedVmid : vmids[0];
                            me.selectContainer(sel);
                        }
                    } catch (e) {
                        console.error('lxcscaler parse error', e);
                    }
                }
            });
        },

        loadConfig: function () {
            var me = this;
            Ext.Ajax.request({
                url: cfgApi(),
                success: function (resp) {
                    try {
                        var cfg = Ext.decode(resp.responseText);
                        var d = cfg.defaults || {};
                        me.down('#cfgMemMin').setValue(d.mem_min_mb);
                        me.down('#cfgMemMax').setValue(d.mem_max_mb);
                        me.down('#cfgMemLow').setValue(Math.round((d.mem_low || 0) * 100));
                        me.down('#cfgMemHigh').setValue(Math.round((d.mem_high || 0) * 100));
                        me.down('#cfgCpuMin').setValue(d.cpu_min);
                        me.down('#cfgCpuMax').setValue(d.cpu_max);
                        me.down('#cfgCpuLow').setValue(Math.round((d.cpu_low || 0) * 100));
                        me.down('#cfgCpuHigh').setValue(Math.round((d.cpu_high || 0) * 100));
                        me.down('#cfgCooldown').setValue(d.cooldown_sec);
                        var ct = cfg.containers || {};
                        me.down('#cfgContainers').setValue(
                            Object.keys(ct).length ? JSON.stringify(ct, null, 2) : ''
                        );
                        me.down('#cfgStatus').update('');
                    } catch (e) {
                        me.down('#cfgStatus').update(
                            '<span style="color:red">Parse error: ' + Ext.htmlEncode(String(e)) + '</span>'
                        );
                    }
                },
                failure: function () {
                    var url = cfgApi();
                    me.down('#cfgStatus').update(
                        '<span style="color:#e8a000">' +
                        'Config API unreachable. ' +
                        '<a href="' + url + '" target="_blank">Click here to accept the certificate</a>' +
                        ', then click Load.</span>'
                    );
                }
            });
        },

        saveConfig: function () {
            var me = this;
            var rawCt = (me.down('#cfgContainers').getValue() || '').trim() || '{}';
            var containers;
            try {
                containers = Ext.decode(rawCt);
            } catch (e) {
                Ext.Msg.alert(gettext('Error'), 'Invalid JSON in per-container overrides: ' + e.message);
                return;
            }
            var cfg = {
                defaults: {
                    mem_min_mb: me.down('#cfgMemMin').getValue(),
                    mem_max_mb: me.down('#cfgMemMax').getValue(),
                    mem_low: (me.down('#cfgMemLow').getValue() || 0) / 100,
                    mem_high: (me.down('#cfgMemHigh').getValue() || 0) / 100,
                    cpu_min: me.down('#cfgCpuMin').getValue(),
                    cpu_max: me.down('#cfgCpuMax').getValue(),
                    cpu_low: (me.down('#cfgCpuLow').getValue() || 0) / 100,
                    cpu_high: (me.down('#cfgCpuHigh').getValue() || 0) / 100,
                    cooldown_sec: me.down('#cfgCooldown').getValue()
                },
                containers: containers
            };
            Ext.Ajax.request({
                url: cfgApi(),
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                rawData: JSON.stringify(cfg),
                success: function () {
                    me.down('#cfgStatus').update(
                        '<span style="color:green">Configuration saved.</span>'
                    );
                },
                failure: function () {
                    me.down('#cfgStatus').update(
                        '<span style="color:red">Save failed.</span>'
                    );
                }
            });
        },

        updateToolbar: function () {
            var me = this;
            var tb = me.getComponent('ctToolbar');
            if (!tb) { return; }
            tb.removeAll();
            tb.add({ xtype: 'tbtext', html: '<b>Container:</b>&nbsp;' });
            Ext.Object.each(me.allData, function (vmid, d) {
                tb.add({
                    text: d.name + ' (' + vmid + ')',
                    enableToggle: true,
                    toggleGroup: 'lxcscaler_ct',
                    pressed: vmid === me.selectedVmid,
                    handler: function () { me.selectContainer(vmid); }
                });
            });
            tb.add('->');
            tb.add({
                iconCls: 'fa fa-refresh',
                tooltip: gettext('Refresh'),
                handler: function () { me.loadData(); }
            });
        },

        selectContainer: function (vmid) {
            var me = this;
            me.selectedVmid = vmid;
            if (!me.allData || !me.allData[vmid]) { return; }
            var hist = me.allData[vmid].history || [];
            var events = me.allData[vmid].events || [];

            var memData = hist.map(function (h) {
                return {
                    time: new Date(h.t * 1000),
                    mem_allocated: (h.mem_mb || 0) * 1048576,
                    mem_used: (h.mem_used_mb || 0) * 1048576
                };
            });
            var cpuData = hist.map(function (h) {
                return {
                    time: new Date(h.t * 1000),
                    cpu_allocated: h.cpu || 0,
                    cpu_used: h.cpu_used || 0
                };
            });
            var eventData = events.map(function (e) {
                var d = new Date(e.t * 1000);
                return {
                    time: d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
                        ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()),
                    resource: e.resource,
                    old: e.old,
                    new_val: e.new_val,
                    dir: e.dir,
                    reason: e.reason
                };
            });

            me.memStore.loadData(memData);
            me.cpuStore.loadData(cpuData);
            me.eventStore.loadData(eventData);
        },

        onDestroy: function () {
            var me = this;
            if (me.refreshTask) { Ext.TaskManager.stop(me.refreshTask); }
            me.callParent();
        }
    });

    Ext.define('PVE.lxcscaler.DcOverride', {
        override: 'PVE.dc.Config',
        initComponent: function () {
            this.callParent(arguments);
            this.insertNodes([{
                xtype: 'pveLxcScalerPanel',
                title: 'LXC Scaler',
                iconCls: 'fa fa-microchip',
                itemId: 'lxcscaler',
                onlineHelp: 'pve_admin_guide'
            }]);
        }
    });

}());
