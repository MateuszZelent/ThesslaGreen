import 'package:flutter_test/flutter_test.dart';

import 'package:thessla_green_mobile/main.dart';

void main() {
  testWidgets('renders the gateway connection form', (WidgetTester tester) async {
    await tester.pumpWidget(const ThesslaGatewayApp());

    expect(find.text('Thessla Green'), findsOneWidget);
    expect(find.text('Połącz i odśwież'), findsOneWidget);
    expect(find.text('URL gatewaya'), findsOneWidget);
  });
}
