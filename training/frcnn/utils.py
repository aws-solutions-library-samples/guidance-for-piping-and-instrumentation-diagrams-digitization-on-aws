import torch
import matplotlib.pyplot as plt
import matplotlib.patches as patches

def draw_boxes_torch(image, boxes, figsize=(15,10)):
    fig, ax = plt.subplots(1, figsize=figsize)
    ax.imshow(image)
    for box in boxes:
        rect = patches.Rectangle(
            (box[1], box[0]),
            box[3]-box[1],
            box[2]-box[0],
            linewidth=2,
            edgecolor='r',
            facecolor='none' # 'none' for transparent fill
            )
        ax.add_patch(rect)
    plt.show()

def draw_boxes(image, boxes, figsize=(15,10)):
    fig, ax = plt.subplots(1, figsize=figsize)
    ax.imshow(image)
    for box in boxes:
        rect = patches.Rectangle(
            (box[0], box[1]),
            box[2]-box[0],
            box[3]-box[1],
            linewidth=2,
            edgecolor='r',
            facecolor='none' # 'none' for transparent fill
            )
        ax.add_patch(rect)
    plt.show()

def save_checkpoint(filename, step, model, optimizer, loss):
    checkpoint = {
        'step': step,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'loss': loss,
    }
    torch.save(checkpoint, f'{filename}_{step}.pth')