import cv2
import keras
import numpy as np
from keras.models import load_model


def show(*args):
    for i, j in enumerate(args):
        cv2.imshow(str(i), j)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def process(img):
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    greyscale = img if len(img.shape) == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    denoise = cv2.GaussianBlur(greyscale, (9, 9), 0)
    thresh = cv2.adaptiveThreshold(denoise, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 11, 2)
    inverted = cv2.bitwise_not(thresh, 0)
    morph = cv2.morphologyEx(inverted, cv2.MORPH_OPEN, kernel)
    dilated = cv2.dilate(morph, kernel, iterations=1)
    return dilated


def get_corners(img):
    contours, hire = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=lambda x: cv2.contourArea(x), reverse=True)
    largest_contour = np.squeeze(contours[0])  # Getting rid of extra dimenstions

    sums = [sum(i) for i in largest_contour]
    differences = [i[0] - i[1] for i in largest_contour]

    top_left = np.argmin(sums)
    top_right = np.argmax(differences)
    bottom_left = np.argmax(sums)
    bottom_right = np.argmin(differences)

    corners = [largest_contour[top_left], largest_contour[top_right], largest_contour[bottom_left],
               largest_contour[bottom_right]]
    return corners


def transform(pts, img):
    pts = np.float32(pts)
    top_l, top_r, bot_l, bot_r = pts[0], pts[1], pts[2], pts[3]

    def pythagoras(pt1, pt2):
        return np.sqrt((pt2[0] - pt1[0]) ** 2 + (pt2[1] - pt1[1]) ** 2)

    width = int(max(pythagoras(bot_r, bot_l), pythagoras(top_r, top_l)))
    height = int(max(pythagoras(top_r, bot_r), pythagoras(top_l, bot_l)))
    square = max(width, height) // 9 * 9  # Making the image dimensions divisible by 9

    dim = np.array(([0, 0], [square - 1, 0], [square - 1, square - 1], [0, square - 1]), dtype='float32')
    matrix = cv2.getPerspectiveTransform(pts, dim)
    warped = cv2.warpPerspective(img, matrix, (square, square))
    return warped


def extract_lines(img):
    length = 12
    horizontal = np.copy(img)
    cols = horizontal.shape[1]
    horizontal_size = cols // length
    horizontal_structure = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_size, 1))
    horizontal = cv2.erode(horizontal, horizontal_structure)
    horizontal = cv2.dilate(horizontal, horizontal_structure)
    vertical = np.copy(img)
    rows = vertical.shape[0]
    vertical_size = rows // length
    vertical_structure = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_size))
    vertical = cv2.erode(vertical, vertical_structure)
    vertical = cv2.dilate(vertical, vertical_structure)
    grid = cv2.add(horizontal, vertical)
    grid = cv2.adaptiveThreshold(grid, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 235, 2)
    grid = cv2.dilate(grid, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=2)
    pts = cv2.HoughLines(grid, .3, np.pi / 90, 200)

    def draw_lines(im, pts):
        im = np.copy(im)
        pts = np.squeeze(pts)
        for r, theta in pts:
            a = np.cos(theta)
            b = np.sin(theta)
            x0 = a * r
            y0 = b * r
            x1 = int(x0 + 1000 * (-b))
            y1 = int(y0 + 1000 * a)
            x2 = int(x0 - 1000 * (-b))
            y2 = int(y0 - 1000 * a)
            cv2.line(im, (x1, y1), (x2, y2), (255, 255, 255), 2)
        return im

    lines = draw_lines(grid, pts)
    mask = cv2.bitwise_not(lines)
    return mask


def extract_digits(img):
    contours, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    img_area = img.shape[0] * img.shape[1]
    digits = []
    for i in contours:
        x, y, w, h = cv2.boundingRect(i)
        if cv2.contourArea(i) > img_area * .0005:  # and round(w / h, 2) in (x / 100 for x in range(60, 91))
            cropped = img[y:y + h, x:x + w]
            digits.append(cropped)
    return digits


def add_border(img_arr):
    digits = []
    for i in img_arr:
        crop_h, crop_w = i.shape
        try:
            pad_h = int(crop_h / 1.75)
            pad_w = (crop_h - crop_w) + pad_h
            pad_h //= 2
            pad_w //= 2
            border = cv2.copyMakeBorder(i, pad_h, pad_h, pad_w, pad_w, cv2.BORDER_CONSTANT, value=(0, 0, 0))
            digits.append(border)
        except cv2.error:
            continue
    return digits


def subdivide(img, divisions=9):
    height, _ = img.shape
    cluster = height // divisions
    subdivided = img.reshape(height // cluster, cluster, -1, cluster).swapaxes(1, 2).reshape(-1, cluster, cluster)
    return [i for i in subdivided]


def sort_digits(subd_arr, template_arr, templates_unsorted, img_dims):
    templates_unsorted = [cv2.resize(i, (img_dims, img_dims), interpolation=cv2.INTER_LANCZOS4) for i in
                          templates_unsorted.copy()]
    base = [cv2.resize(i, (img_dims, img_dims), interpolation=cv2.INTER_LANCZOS4) for i in subd_arr.copy()]
    base = np.zeros_like(base)
    for idx, template in enumerate(template_arr):
        h, w = template.shape
        for idx2, img in enumerate(subd_arr):
            res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
            found = np.where(res >= .8)
            # I dont know why I need this here, but I can't delete it.
            for pt in zip(*found[::-1]):
                cv2.rectangle(img, pt, (pt[0] + w, pt[1] + h), (255, 255, 255), 2)
            if list(zip(*found[::-1])):  # If template matched
                base[idx2] = templates_unsorted[idx]
                break
    return base


def ocr(img_array, img_dims):
    for i in img_array:
        resized = cv2.resize(i, (img_dims, img_dims), interpolation=cv2.INTER_LANCZOS4)
        img = np.array([resized])
        img = img.reshape(img.shape[0], img_dims, img_dims, 1)
        img = img.astype('float32')
        img /= 255
        classes = model.predict_classes(img)
        print(classes[0])
        show(resized)


model = load_model('ocr/chars74k_V02.hdf5')
model.compile(loss=keras.losses.categorical_crossentropy,
              optimizer=keras.optimizers.Adadelta(),
              metrics=['accuracy'])
img_dims = 28

img = cv2.imread('assets/c1.jpg', cv2.IMREAD_GRAYSCALE)
old_height, old_width = img.shape
size = 800
if img.shape[0] >= size:
    aspect_ratio = size / float(old_height)
    dim = (int(old_width * aspect_ratio), size)
    img = cv2.resize(img, dim, interpolation=cv2.INTER_LANCZOS4)
elif img.shape[1] >= size:
    aspect_ratio = size / float(old_width)
    dim = (size, int(old_height * aspect_ratio))
    img = cv2.resize(img, dim, interpolation=cv2.INTER_LANCZOS4)

processed = process(img)
corners = get_corners(processed)
warped = transform(corners, processed)
mask = extract_lines(warped)
numbers = cv2.bitwise_and(warped, mask)
digits_unsorted = extract_digits(numbers)
digits_border = add_border(digits_unsorted)
digits_subd = subdivide(numbers)
digits_sorted = sort_digits(digits_subd, digits_unsorted, digits_border, digits_unsorted[0].shape[0])
for i in digits_sorted:
    show(warped, i)
