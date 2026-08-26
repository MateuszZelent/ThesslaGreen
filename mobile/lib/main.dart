import 'dart:async';

import 'package:flutter/material.dart';

import 'thessla_gateway_client.dart';

void main() {
  runApp(const ThesslaGatewayApp());
}

class ThesslaGatewayApp extends StatelessWidget {
  const ThesslaGatewayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Thessla Green',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.teal),
        useMaterial3: true,
      ),
      home: const GatewayPage(),
    );
  }
}

class GatewayPage extends StatefulWidget {
  const GatewayPage({super.key});

  @override
  State<GatewayPage> createState() => _GatewayPageState();
}

class _GatewayPageState extends State<GatewayPage> {
  static const _modeNames = <String>['automatic', 'manual', 'temporary'];
  static const _modeLabels = <String, String>{
    'automatic': 'Automatyczny',
    'manual': 'Ręczny',
    'temporary': 'Chwilowy',
  };
  static const _modeDescriptions = <String, String>{
    'automatic': 'Centrala pracuje według harmonogramu skonfigurowanego w Air++.',
    'manual': 'Wybrana intensywność działa bez limitu czasu, aż zmienisz tryb.',
    'temporary': 'Wybrana intensywność działa przez czas skonfigurowany w Air++.',
  };
  static const _specialModeNames = <String>[
    'none',
    'hood',
    'fireplace',
    'airing_manual',
    'open_windows',
    'empty_house',
  ];

  final _baseUriController = TextEditingController(text: 'http://127.0.0.1:8000');
  final _tokenController = TextEditingController();
  ThesslaGatewayClient? _client;
  Timer? _pollTimer;
  GatewayState? _state;
  double _requestedSpeed = 40;
  String? _selectedMode;
  String? _selectedSpecialMode;
  String? _error;
  String? _confirmation;
  bool _busy = false;

  @override
  void dispose() {
    _pollTimer?.cancel();
    _client?.close();
    _baseUriController.dispose();
    _tokenController.dispose();
    super.dispose();
  }

  ThesslaGatewayClient _clientForForm() {
    final rawUri = _baseUriController.text.trim();
    final uri = Uri.tryParse(rawUri);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      throw const ThesslaGatewayException('Podaj poprawny adres gatewaya.');
    }
    if (uri.scheme != 'http' && uri.scheme != 'https') {
      throw const ThesslaGatewayException('Gateway musi używać HTTP albo HTTPS.');
    }
    _client?.close();
    final client = ThesslaGatewayClient(
      baseUri: uri,
      apiToken: _tokenController.text.trim().isEmpty ? null : _tokenController.text.trim(),
    );
    _client = client;
    return client;
  }

  ThesslaGatewayClient _requireClient() {
    return _client ?? _clientForForm();
  }

  Future<void> _connect() async {
    await _run(() async {
      final client = _clientForForm();
      final state = await client.getState();
      if (!mounted) return;
      setState(() {
        _state = state;
        _requestedSpeed = (state.editableFanSpeed ?? 40).toDouble().clamp(10, 100).toDouble();
        _selectedMode = _modeName(state.mode);
        _selectedSpecialMode = _specialModeName(state.values['special_mode']);
        _error = null;
        _confirmation = null;
      });
      _startPolling();
    });
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      unawaited(_refresh(silent: true));
    });
  }

  Future<void> _refresh({bool silent = false}) async {
    try {
      final state = await _requireClient().getState();
      if (!mounted) return;
      setState(() {
        _state = state;
        _requestedSpeed = (state.editableFanSpeed ?? _requestedSpeed)
            .toDouble()
            .clamp(10, 100)
            .toDouble();
        _selectedMode = _modeName(state.mode);
        _selectedSpecialMode = _specialModeName(state.values['special_mode']);
        if (!silent) _error = null;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    }
  }

  Future<void> _sendCommand(String type, Map<String, Object?> parameters) async {
    final current = _state;
    if (current == null) {
      throw const ThesslaGatewayException('Najpierw połącz się z gatewayem.');
    }
    final response = await _requireClient().sendCommand(
      type: type,
      parameters: parameters,
      requestId: 'flutter-${DateTime.now().microsecondsSinceEpoch}',
      expectedRevision: current.revision,
    );
    if (!mounted) return;
    setState(() {
      // The screen adopts only the confirmed snapshot returned by the gateway.
      _state = response.state;
      _requestedSpeed = (response.state.editableFanSpeed ?? _requestedSpeed)
          .toDouble()
          .clamp(10, 100)
          .toDouble();
      _selectedMode = _modeName(response.state.mode);
      _selectedSpecialMode = _specialModeName(response.state.values['special_mode']);
      _error = null;
      var confirmation = response.confirmed
          ? (response.replayed
              ? 'Polecenie odtworzone bez drugiego zapisu.'
              : 'Polecenie potwierdzone read-backiem.')
          : 'Gateway nie potwierdził polecenia.';
      final airflow = response.result['airflow_observation'];
      if (response.confirmed && airflow is Map && airflow['available'] == true) {
        confirmation +=
            ' Przepływ: nawiew ${airflow['after_supply_airflow_m3h']} m³/h, '
            'wywiew ${airflow['after_extract_airflow_m3h']} m³/h.';
      }
      _confirmation = confirmation;
    });
  }

  Future<void> _setSpeed() async {
    await _run(() async {
      if (_state?.mode == 2) {
        await _sendCommand(
          'activate_temporary_mode',
          {'percentage': _requestedSpeed.round()},
        );
        return;
      }
      if (_state?.mode != 1) {
        await _sendCommand('set_mode', {'mode': 'manual'});
      }
      await _sendCommand('set_fan_speed', {'percentage': _requestedSpeed.round()});
    });
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on Object catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = _state;
    final values = state?.values ?? const <String, dynamic>{};
    final activeSupply = state?.supplyPercentage;
    final activeExtract = state?.extractPercentage;
    final powerOn = state?.powerOn ?? false;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Thessla Green'),
        actions: [
          IconButton(
            onPressed: _busy ? null : () => unawaited(_refresh()),
            icon: const Icon(Icons.refresh),
            tooltip: 'Odśwież',
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _connectionCard(),
          if (_error != null) ...[
            const SizedBox(height: 12),
            _messageCard(_error!, isError: true),
          ],
          if (_confirmation != null) ...[
            const SizedBox(height: 12),
            _messageCard(_confirmation!),
          ],
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    state?.identity?.model ?? 'Brak połączenia',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    state == null
                        ? '—'
                        : '${state.online ? 'Online' : 'Offline'} · revision ${state.revision}',
                  ),
                  const SizedBox(height: 12),
                  _metricRow(
                    'Zadane: nawiew / wywiew',
                    activeSupply == null || activeExtract == null
                        ? '—'
                        : '$activeSupply% / $activeExtract%',
                  ),
                  _metricRow('Nawiew', _formatMetric(values['supply_flowrate'], 'm³/h')),
                  _metricRow('Wywiew', _formatMetric(values['extract_flowrate'], 'm³/h')),
                  _metricRow(
                    'Temperatura zewnętrzna',
                    _formatMetric(values['outdoor_temperature'], '°C'),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Sterowanie', style: Theme.of(context).textTheme.titleLarge),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: _selectedMode,
                    decoration: const InputDecoration(labelText: 'Tryb pracy'),
                    items: _modeNames
                        .map(
                          (name) => DropdownMenuItem(
                            value: name,
                            child: Text(_modeLabels[name] ?? name),
                          ),
                        )
                        .toList(),
                    onChanged: _busy ? null : (value) {
                      if (value != null) {
                        unawaited(
                          _run(
                            () => value == 'temporary'
                                ? _sendCommand(
                                    'activate_temporary_mode',
                                    {'percentage': _requestedSpeed.round()},
                                  )
                                : _sendCommand('set_mode', {'mode': value}),
                          ),
                        );
                      }
                    },
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _modeDescriptions[_selectedMode] ?? 'Wybierz tryb pracy centrali.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    '${_state?.mode == 2 ? 'Nastawa tymczasowa' : 'Nastawa manualna'}: '
                    '${_requestedSpeed.round()}%',
                  ),
                  Slider(
                    value: _requestedSpeed,
                    min: 10,
                    max: 100,
                    divisions: 90,
                    label: '${_requestedSpeed.round()}%',
                    onChanged: _busy ? null : (value) => setState(() => _requestedSpeed = value),
                  ),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: _busy || state == null ? null : () => unawaited(_setSpeed()),
                      icon: const Icon(Icons.tune),
                      label: Text(
                        state?.mode == 2
                            ? 'Ustaw prędkość tymczasową'
                            : state?.mode == 0
                                ? 'Ustaw i przełącz na manualny'
                                : 'Ustaw prędkość manualną',
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: _selectedSpecialMode,
                    decoration: const InputDecoration(labelText: 'Tryb specjalny'),
                    items: _specialModeNames
                        .map((name) => DropdownMenuItem(value: name, child: Text(name)))
                        .toList(),
                    onChanged: _busy ? null : (value) {
                      if (value != null) {
                        unawaited(
                          _run(() => _sendCommand('set_special_mode', {'mode': value})),
                        );
                      }
                    },
                  ),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      onPressed: _busy || state == null
                          ? null
                          : () => unawaited(
                              _run(
                                () => _sendCommand(
                                  'set_power',
                                  {'enabled': !powerOn},
                                ),
                              ),
                            ),
                      icon: Icon(
                        state?.powerOn == true ? Icons.power_settings_new : Icons.power,
                      ),
                      label: Text(
                        state?.powerOn == true ? 'Wyłącz centralę' : 'Włącz centralę',
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (_busy)
            const Padding(
              padding: EdgeInsets.only(top: 16),
              child: LinearProgressIndicator(),
            ),
        ],
      ),
    );
  }

  Widget _connectionCard() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            TextField(
              controller: _baseUriController,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(labelText: 'URL gatewaya'),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _tokenController,
              obscureText: true,
              decoration: const InputDecoration(labelText: 'Token API (opcjonalnie)'),
            ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: _busy ? null : () => unawaited(_connect()),
                icon: const Icon(Icons.link),
                label: const Text('Połącz i odśwież'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _messageCard(String message, {bool isError = false}) {
    return Card(
      color: isError
          ? Theme.of(context).colorScheme.errorContainer
          : Theme.of(context).colorScheme.primaryContainer,
      child: Padding(padding: const EdgeInsets.all(12), child: Text(message)),
    );
  }

  Widget _metricRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [Text(label), Text(value, style: const TextStyle(fontWeight: FontWeight.bold))],
      ),
    );
  }

  static String _formatMetric(Object? value, String unit) {
    if (value is num) return '${value.toStringAsFixed(value is int ? 0 : 1)} $unit';
    return '—';
  }

  static String? _modeName(int? mode) {
    const names = <int, String>{0: 'automatic', 1: 'manual', 2: 'temporary'};
    return names[mode];
  }

  static String? _specialModeName(Object? value) {
    if (value is! num) return null;
    const names = <int, String>{
      0: 'none',
      1: 'hood',
      2: 'fireplace',
      7: 'airing_manual',
      10: 'open_windows',
      11: 'empty_house',
    };
    return names[value.toInt()];
  }
}
