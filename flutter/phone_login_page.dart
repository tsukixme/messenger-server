// Экран входа по номеру телефона с подтверждением через WhatsApp.
// Положите файл в lib/pages/phone_login/phone_login_page.dart вашего форка FluffyChat.
// Пакеты http и url_launcher в FluffyChat уже есть.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';

/// Адрес сервиса входа. Замените на свой домен ngrok.
const String kAuthBaseUrl = 'https://your-name.ngrok-free.app/auth';

/// Вызывается, когда номер подтверждён: здесь приложение входит в Matrix.
typedef OnCredentials = Future<void> Function(String userId, String password);

class PhoneLoginPage extends StatefulWidget {
  final OnCredentials onCredentials;
  const PhoneLoginPage({super.key, required this.onCredentials});

  @override
  State<PhoneLoginPage> createState() => _PhoneLoginPageState();
}

class _PhoneLoginPageState extends State<PhoneLoginPage> {
  final _phone = TextEditingController();
  String? _sessionId;
  String? _code;
  String? _waLink;
  String? _error;
  bool _busy = false;
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    _phone.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await http.post(
        Uri.parse('$kAuthBaseUrl/start'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'phone': _phone.text}),
      );
      final data = jsonDecode(utf8.decode(r.bodyBytes));
      if (r.statusCode != 200) throw data['detail'] ?? 'Ошибка ${r.statusCode}';
      setState(() {
        _sessionId = data['session_id'];
        _code = data['code'];
        _waLink = data['wa_link'];
      });
      _timer?.cancel();
      _timer = Timer.periodic(const Duration(seconds: 2), (_) => _poll());
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _poll() async {
    if (_sessionId == null) return;
    try {
      final r = await http.get(Uri.parse('$kAuthBaseUrl/status/$_sessionId'));
      if (r.statusCode == 410) {
        _timer?.cancel();
        setState(() {
          _sessionId = null;
          _error = 'Код истёк, начните заново';
        });
        return;
      }
      if (r.statusCode != 200) return;
      final data = jsonDecode(utf8.decode(r.bodyBytes));
      if (data['verified'] == true) {
        _timer?.cancel();
        setState(() => _busy = true);
        await widget.onCredentials(data['user_id'], data['password']);
      }
    } catch (e) {
      _timer?.cancel();
      if (mounted) {
        setState(() {
          _busy = false;
          _error = e.toString();
        });
      }
    }
  }

  Future<void> _openWhatsApp() async {
    if (_waLink == null) return;
    await launchUrl(Uri.parse(_waLink!), mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final waiting = _sessionId != null;
    return Scaffold(
      appBar: AppBar(title: const Text('Вход по номеру')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          if (!waiting) ...[
            TextField(
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                labelText: 'Номер телефона',
                hintText: '+7 701 123 45 67',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: _busy ? null : _start,
              child: const Text('Продолжить'),
            ),
          ] else ...[
            const Text('Отправьте этот код нам в WhatsApp:'),
            const SizedBox(height: 12),
            SelectableText(
              _code ?? '',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.displaySmall,
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _waLink == null ? null : _openWhatsApp,
              icon: const Icon(Icons.send),
              label: const Text('Открыть WhatsApp'),
            ),
            const SizedBox(height: 24),
            const Center(child: CircularProgressIndicator()),
            const SizedBox(height: 8),
            const Text('Ждём подтверждения…', textAlign: TextAlign.center),
          ],
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ],
      ),
    );
  }
}
