/// Small typed Dart client for the versioned Thessla Green gateway API.
///
/// The client deliberately has no optimistic state. A command is considered
/// applied only when the gateway returns `status: confirmed` and a read-back
/// snapshot. Callers must reuse the same requestId when retrying a request.
library thessla_gateway_client;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

class ThesslaGatewayException implements Exception {
  const ThesslaGatewayException(this.message, {this.statusCode, this.detail});

  final String message;
  final int? statusCode;
  final Object? detail;

  @override
  String toString() {
    final suffix = statusCode == null ? '' : ' (HTTP $statusCode)';
    return 'ThesslaGatewayException$suffix: $message';
  }
}

class GatewayDeviceIdentity {
  GatewayDeviceIdentity({
    required this.model,
    required this.unitId,
    required this.stableId,
    this.firmware,
    this.serialNumber,
    this.endpoint,
  });

  factory GatewayDeviceIdentity.fromJson(Map<String, dynamic> json) {
    return GatewayDeviceIdentity(
      model: _string(json['model'], 'identity.model'),
      unitId: _int(json['unit_id'], 'identity.unit_id'),
      stableId: _string(json['stable_id'], 'identity.stable_id'),
      firmware: json['firmware'] as String?,
      serialNumber: json['serial_number'] as String?,
      endpoint: json['endpoint'] is Map
          ? Map<String, dynamic>.from(json['endpoint'] as Map)
          : null,
    );
  }

  final String model;
  final int unitId;
  final String stableId;
  final String? firmware;
  final String? serialNumber;
  final Map<String, dynamic>? endpoint;
}

class GatewayState {
  GatewayState({
    required this.revision,
    required this.capturedAt,
    required this.online,
    required this.values,
    required this.quality,
    required this.capabilities,
    this.identity,
    this.error,
  });

  factory GatewayState.fromJson(Map<String, dynamic> json) {
    final identityJson = json['identity'];
    final capabilitiesJson = json['capabilities'];
    final valuesJson = json['values'];
    return GatewayState(
      revision: _int(json['revision'], 'state.revision'),
      capturedAt: DateTime.tryParse(json['captured_at'] as String? ?? ''),
      online: json['online'] == true,
      values: valuesJson is Map
          ? Map<String, dynamic>.from(valuesJson)
          : <String, dynamic>{},
      quality: json['quality'] as String? ?? 'unknown',
      capabilities: capabilitiesJson is Map
          ? Map<String, dynamic>.from(capabilitiesJson)
          : <String, dynamic>{},
      identity: identityJson is Map
          ? GatewayDeviceIdentity.fromJson(Map<String, dynamic>.from(identityJson))
          : null,
      error: json['error'] as String?,
    );
  }

  final int revision;
  final DateTime? capturedAt;
  final bool online;
  final Map<String, dynamic> values;
  final String quality;
  final Map<String, dynamic> capabilities;
  final GatewayDeviceIdentity? identity;
  final String? error;

  int? get manualFanSpeed => _nullableInt(values['manual_fan_speed']);
  int? get temporaryFanSpeed => _nullableInt(values['temporary_fan_speed']);
  int? get mode => _nullableInt(values['mode']);
  int? get supplyAirflow => _nullableInt(values['supply_airflow']);
  int? get extractAirflow => _nullableInt(values['extract_airflow']);
  int? get activeFanSpeed => mode == 2 ? temporaryFanSpeed : manualFanSpeed;
}

class GatewayCommandResponse {
  GatewayCommandResponse({
    required this.status,
    required this.replayed,
    required this.result,
    required this.state,
    this.requestId,
  });

  factory GatewayCommandResponse.fromJson(Map<String, dynamic> json) {
    final resultJson = json['result'];
    final stateJson = json['state'];
    if (resultJson is! Map || stateJson is! Map) {
      throw const ThesslaGatewayException('command response is missing result or state');
    }
    return GatewayCommandResponse(
      status: _string(json['status'], 'command.status'),
      replayed: json['replayed'] == true,
      requestId: json['request_id'] as String?,
      result: Map<String, dynamic>.from(resultJson),
      state: GatewayState.fromJson(Map<String, dynamic>.from(stateJson)),
    );
  }

  final String status;
  final bool replayed;
  final String? requestId;
  final Map<String, dynamic> result;
  final GatewayState state;

  bool get confirmed => status == 'confirmed' && result['confirmed'] == true;
  int? get confirmedValue => _nullableInt(result['confirmed_value']);
}

class ThesslaGatewayClient {
  ThesslaGatewayClient({
    required Uri baseUri,
    this.apiToken,
    http.Client? httpClient,
  })  : _baseUri = baseUri,
        _httpClient = httpClient ?? http.Client(),
        _ownsHttpClient = httpClient == null;

  final Uri _baseUri;
  final String? apiToken;
  final http.Client _httpClient;
  final bool _ownsHttpClient;

  Future<GatewayState> getState() async {
    return GatewayState.fromJson(await _get('/api/v1/state'));
  }

  Future<List<GatewayDeviceIdentity>> getDevices() async {
    final body = await _get('/api/v1/devices');
    final devices = body['devices'];
    if (devices is! List) {
      throw const ThesslaGatewayException('devices response is not a list');
    }
    return devices
        .whereType<Map>()
        .map((device) => GatewayDeviceIdentity.fromJson(Map<String, dynamic>.from(device)))
        .toList(growable: false);
  }

  Future<Map<String, dynamic>> getCapabilities() {
    return _get('/api/v1/capabilities');
  }

  Future<Map<String, dynamic>> getControlOptions() {
    return _get('/api/v1/control/options');
  }

  Future<List<Map<String, dynamic>>> getTelemetry(
    String deviceId, {
    int limit = 100,
    DateTime? from,
    DateTime? to,
  }) async {
    final query = <String, String>{'limit': '$limit'};
    if (from != null) query['from'] = from.toUtc().toIso8601String();
    if (to != null) query['to'] = to.toUtc().toIso8601String();
    final body = await _get('/api/v1/devices/$deviceId/telemetry', query: query);
    final points = body['points'];
    if (points is! List) {
      throw const ThesslaGatewayException('telemetry response is not a list');
    }
    return points
        .whereType<Map>()
        .map((point) => Map<String, dynamic>.from(point))
        .toList(growable: false);
  }

  Future<GatewayCommandResponse> sendCommand({
    required String type,
    required Map<String, Object?> parameters,
    required String requestId,
    int? expectedRevision,
  }) async {
    if (requestId.trim().isEmpty) {
      throw ArgumentError.value(requestId, 'requestId', 'must not be empty');
    }
    final body = <String, Object?>{
      'type': type,
      'parameters': parameters,
      'request_id': requestId,
      if (expectedRevision != null) 'expected_revision': expectedRevision,
    };
    return GatewayCommandResponse.fromJson(
      await _request(
        'POST',
        '/api/v1/commands',
        body,
        extraHeaders: const <String, String>{'X-Thessla-Source': 'mobile'},
      ),
    );
  }

  /// Emits state events. On reconnect, call [getState] before subscribing again.
  Stream<Map<String, dynamic>> events() async* {
    final uri = _appendPath('/api/v1/events');
    final socketUri = uri.replace(
      scheme: uri.scheme == 'https' ? 'wss' : 'ws',
    );
    final channel = WebSocketChannel.connect(
      socketUri,
      headers: _headers(),
    );
    try {
      await channel.ready;
      await for (final message in channel.stream) {
        if (message is! String) continue;
        final decoded = jsonDecode(message);
        if (decoded is Map) {
          yield Map<String, dynamic>.from(decoded);
        }
      }
    } finally {
      await channel.sink.close();
    }
  }

  void close() {
    if (_ownsHttpClient) _httpClient.close();
  }

  Future<Map<String, dynamic>> _get(
    String path, {
    Map<String, String>? query,
  }) {
    return _request('GET', path, null, query: query);
  }

  Future<Map<String, dynamic>> _request(
    String method,
    String path,
    Object? body, {
    Map<String, String>? query,
    Map<String, String>? extraHeaders,
  }) async {
    final request = http.Request(method, _appendPath(path, query: query));
    request.headers.addAll(_headers());
    if (extraHeaders != null) request.headers.addAll(extraHeaders);
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }
    try {
      final response = await _httpClient.send(request);
      final text = await response.stream.bytesToString();
      dynamic decoded;
      if (text.isNotEmpty) decoded = jsonDecode(text);
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw ThesslaGatewayException(
          'gateway request failed',
          statusCode: response.statusCode,
          detail: decoded,
        );
      }
      if (decoded is! Map) {
        throw const ThesslaGatewayException('gateway response is not a JSON object');
      }
      return Map<String, dynamic>.from(decoded);
    } on ThesslaGatewayException {
      rethrow;
    } on Object catch (error) {
      throw ThesslaGatewayException('gateway request could not be completed: $error');
    }
  }

  Map<String, String> _headers() {
    return <String, String>{
      'Accept': 'application/json',
      if (apiToken != null && apiToken!.isNotEmpty)
        'Authorization': 'Bearer $apiToken',
    };
  }

  Uri _appendPath(String path, {Map<String, String>? query}) {
    final basePath = _baseUri.path.endsWith('/')
        ? _baseUri.path.substring(0, _baseUri.path.length - 1)
        : _baseUri.path;
    return _baseUri.replace(
      path: '$basePath$path',
      queryParameters: query,
    );
  }
}

String _string(Object? value, String name) {
  if (value is String && value.isNotEmpty) return value;
  throw ThesslaGatewayException('missing or invalid $name');
}

int _int(Object? value, String name) {
  if (value is int) return value;
  throw ThesslaGatewayException('missing or invalid $name');
}

int? _nullableInt(Object? value) => value is int ? value : null;
