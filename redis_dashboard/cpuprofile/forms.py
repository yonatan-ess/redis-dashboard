from django import forms


class CaptureForm(forms.Form):
    host = forms.CharField(initial='localhost', max_length=255)
    port = forms.IntegerField(initial=6379, min_value=1, max_value=65535)
    db = forms.IntegerField(initial=0, min_value=0, label='DB')
    username = forms.CharField(required=False, max_length=255)
    password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=True))

    amount = forms.IntegerField(initial=500, min_value=2, max_value=100_000,
                                label='Commands per sample')
    samples_requested = forms.IntegerField(initial=36, min_value=1, max_value=1000, label='Samples')
    interval = forms.FloatField(initial=0.3, min_value=0, max_value=3600, label='Pause between (s)')
    max_sample_seconds = forms.FloatField(initial=5, min_value=0.1, max_value=300,
                                          label='Max sample time (s)')

    warn_usec = forms.FloatField(initial=20, min_value=0, label='Warn at (µs/call)')
    crit_usec = forms.FloatField(initial=100, min_value=0, label='Critical at (µs/call)')

    def clean(self):
        data = super().clean()
        if data.get('warn_usec') is not None and data.get('crit_usec') is not None \
                and data['warn_usec'] > data['crit_usec']:
            self.add_error('crit_usec', 'Must be ≥ the warn threshold.')
        return data
