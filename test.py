import numpy as np
import matplotlib.pyplot as plt

# Загрузка данных из файла
filename = r'C:\Users\root\Documents\Eugene\Programming\Python\Telegram Bots\LabAssistant [DEV]\1.txt'  # Замените на ваш файл
data = np.loadtxt(filename)  # Предполагаем, что файл имеет две колонки: длина волны и интенсивность
wavelengths = data[:, 0]  # Первая колонка - длина волны
intensities = data[:, 1]  # Вторая колонка - интенсивность

# Нахождение положения пика
peak_index = np.argmax(intensities)
peak_wavelength = wavelengths[peak_index]
peak_intensity = intensities[peak_index]

# Определение уровня полувысоты
half_max = peak_intensity / 2

# Находим ширину на полувысоте
# Слева от пика
left_half_max_index = np.where(intensities[:peak_index] <= half_max)[0][-1]
left_half_max_wavelength = wavelengths[left_half_max_index]

# Справа от пика
right_half_max_index = np.where(intensities[peak_index:] <= half_max)[0][0] + peak_index
right_half_max_wavelength = wavelengths[right_half_max_index]

# Ширина на полувысоте
fwhm = right_half_max_wavelength - left_half_max_wavelength

# Построение графика
plt.figure(figsize=(10, 6))
plt.plot(wavelengths, intensities, label='Spectrum', color='b')
plt.axhline(half_max, color='grey', linestyle='--', label='Half Maximum')
plt.plot(peak_wavelength, peak_intensity, 'ro', label=f'Peak at {peak_wavelength:.2f} nm')
plt.plot([left_half_max_wavelength, right_half_max_wavelength], [half_max, half_max], 'go-', label=f'FWHM = {fwhm:.2f} nm')

# Подписи и легенда
plt.xlabel('Wavelength (nm)')
plt.ylabel('Intensity (a.u.)')
plt.title('Spectrum with Peak and FWHM')
plt.legend()
plt.grid(True)
plt.savefig("spectrum_analysis.png")
